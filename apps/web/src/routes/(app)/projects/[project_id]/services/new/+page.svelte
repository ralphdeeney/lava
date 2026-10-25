<script lang="ts">
  import { goto } from '$app/navigation';
  import ServiceForm from '$lib/ServiceForm.svelte';
  import { mutate } from '$lib/client';
  import type { Service } from '$lib/models';
  let { data } = $props(); let pending = $state(false); let message = $state('');
  async function create(value: { name: string; service_type: Service['service_type']; desired_state: 'stopped' | 'running'; resources: { cpu: number; memory_mb: number } }) {
    pending = true; message = '';
    try { const service = await mutate<Service>(`/projects/${data.project.id}/services`, 'POST', data.session.csrf_token, value); await goto(`/projects/${data.project.id}/services/${service.id}`, { invalidateAll: true }); }
    catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to create service.'; }
    finally { pending = false; }
  }
</script>
<svelte:head><title>Create service · LAVA</title></svelte:head>
<a class="back-link" href={`/projects/${data.project.id}`}>← {data.project.name}</a>
<div class="page-heading"><div><h1>Create service</h1><p class="muted">Register service configuration in {data.project.name}.</p></div></div>
<section class="panel form-panel">
  {#if message}<p role="alert" class="notice">{message}</p>{/if}
  <ServiceForm pending={pending} disabled={data.project.lifecycle_status === 'archived'} submitLabel="Create service" onsubmit={create} />
</section>
