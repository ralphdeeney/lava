<script lang="ts">
  import { goto, invalidateAll } from '$app/navigation';
  import ServiceForm from '$lib/ServiceForm.svelte';
  import { mutate } from '$lib/client';
  import type { Service } from '$lib/models';
  let { data } = $props(); let pending = $state(false); let message = $state(''); let saved = $state(false);
  async function save(value: { name: string; service_type: Service['service_type']; desired_state: 'stopped' | 'running'; resources: { cpu: number; memory_mb: number } }) {
    pending = true; message = ''; saved = false;
    try { await mutate(`/projects/${data.project.id}/services/${data.service.id}`, 'PATCH', data.session.csrf_token, value); await invalidateAll(); saved = true; }
    catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to save configuration.'; }
    finally { pending = false; }
  }
  async function archive() {
    if (!confirm('Archive this service? Future configuration changes will be disabled.')) return;
    pending = true; message = '';
    try { await mutate(`/projects/${data.project.id}/services/${data.service.id}`, 'DELETE', data.session.csrf_token); await goto(`/projects/${data.project.id}`, { invalidateAll: true }); }
    catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to archive service.'; }
    finally { pending = false; }
  }
</script>
<svelte:head><title>{data.service.name} · LAVA</title></svelte:head>
<a class="back-link" href={`/projects/${data.project.id}`}>← {data.project.name}</a>
<div class="page-heading"><div><p class="eyebrow">SERVICE CONFIGURATION</p><h1>{data.service.name}</h1></div><span class="badge">{data.service.desired_state}</span></div>
{#if message}<p role="alert" class="notice">{message}</p>{/if}
{#if saved}<p role="status" class="success">Configuration saved.</p>{/if}
<section class="panel form-panel" aria-labelledby="configuration-title">
  <h2 id="configuration-title">Configuration</h2>
  <ServiceForm initial={data.service} pending={pending} disabled={data.service.desired_state === 'archived' || data.project.lifecycle_status === 'archived'} submitLabel="Save configuration" onsubmit={save} />
</section>
{#if data.service.desired_state !== 'archived' && data.project.lifecycle_status === 'active'}<section class="panel"><h2>Archive service</h2><p class="muted">Keep the record while preventing future changes.</p><button class="secondary danger" disabled={pending} onclick={archive}>Archive service</button></section>{/if}
