-- Dedicated private runtime only. No changes to application/auth tables.
begin;
create table if not exists public.drift_runtime (
  name text primary key,
  value jsonb not null default '{"sources":{}}'::jsonb,
  owner uuid,
  lease_until timestamptz not null default '-infinity',
  last_started timestamptz,
  last_finished timestamptz,
  last_ok boolean,
  updated_at timestamptz not null default now()
);
alter table public.drift_runtime enable row level security;
revoke all on public.drift_runtime from public, anon, authenticated;
grant select, insert, update on public.drift_runtime to service_role;

create or replace function public.drift_claim(p_name text, p_token uuid, p_seconds int, p_interval int)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare acquired text;
begin
  if p_name not in ('youtube','calendar','digest') or p_seconds not between 60 and 900
     or p_interval not between 0 and 3600 then
    raise exception 'Invalid job configuration';
  end if;
  insert into public.drift_runtime(name) values (p_name) on conflict do nothing;
  update public.drift_runtime set owner=p_token, lease_until=now()+make_interval(secs=>p_seconds),
    last_started=now(), updated_at=now()
    where name=p_name and lease_until<=now()
      and (last_started is null or last_started<=now()-make_interval(secs=>p_interval))
    returning name into acquired;
  return acquired is not null;
end $$;

create or replace function public.drift_read(p_name text)
returns jsonb language sql security invoker set search_path = '' as $$
  select coalesce((select value from public.drift_runtime where name=p_name), '{"sources":{}}'::jsonb);
$$;

create or replace function public.drift_owned(p_name text, p_token uuid)
returns boolean language sql security invoker set search_path = '' as $$
  select exists(select 1 from public.drift_runtime where name=p_name and owner=p_token and lease_until>now());
$$;

create or replace function public.drift_write(p_name text, p_token uuid, p_value jsonb)
returns boolean language plpgsql security invoker set search_path = '' as $$
begin
  if jsonb_typeof(p_value)<>'object' or octet_length(p_value::text)>2000000 then
    raise exception 'State must be an object smaller than 2 MB';
  end if;
  update public.drift_runtime set value=p_value, updated_at=now()
    where name=p_name and owner=p_token and lease_until>now();
  return found;
end $$;

create or replace function public.drift_finish(p_name text, p_token uuid, p_ok boolean)
returns boolean language plpgsql security invoker set search_path = '' as $$
begin
  update public.drift_runtime set owner=null, lease_until='-infinity',
    last_finished=now(), last_ok=p_ok, updated_at=now()
    where name=p_name and owner=p_token and lease_until>now();
  return found;
end $$;

create or replace function public.drift_status()
returns jsonb language sql security invoker set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object('name',name,'last_started',last_started,
    'last_finished',last_finished,'last_ok',last_ok,'lease_until',lease_until)), '[]'::jsonb)
  from public.drift_runtime;
$$;

revoke all on function public.drift_claim(text,uuid,int,int) from public,anon,authenticated;
revoke all on function public.drift_read(text) from public,anon,authenticated;
revoke all on function public.drift_owned(text,uuid) from public,anon,authenticated;
revoke all on function public.drift_write(text,uuid,jsonb) from public,anon,authenticated;
revoke all on function public.drift_finish(text,uuid,boolean) from public,anon,authenticated;
revoke all on function public.drift_status() from public,anon,authenticated;
grant execute on function public.drift_claim(text,uuid,int,int) to service_role;
grant execute on function public.drift_read(text) to service_role;
grant execute on function public.drift_owned(text,uuid) to service_role;
grant execute on function public.drift_write(text,uuid,jsonb) to service_role;
grant execute on function public.drift_finish(text,uuid,boolean) to service_role;
grant execute on function public.drift_status() to service_role;
commit;
