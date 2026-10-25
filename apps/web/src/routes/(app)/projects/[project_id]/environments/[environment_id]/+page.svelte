<script lang="ts">
  import { goto, invalidateAll } from '$app/navigation';
  import { mutate } from '$lib/client';
  let { data } = $props();
  let name = $state(''); let description = $state(''); let pending = $state(false); let message = $state(''); let success = $state('');
  $effect(() => { name = data.environment.name; description = data.environment.description; });
  const canConfigure = $derived(data.environment.lifecycle_status === 'active' && data.project.lifecycle_status === 'active' && ['owner', 'admin', 'developer'].includes(data.project.my_role));
  const base = $derived(`/projects/${data.project.id}/environments/${data.environment.id}`);
  async function save(event: SubmitEvent) {
    event.preventDefault(); pending = true; message = ''; success = '';
    try { await mutate(base, 'PATCH', data.session.csrf_token, { name, description }); await invalidateAll(); success = 'Environment saved.'; }
    catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to save environment.'; }
    finally { pending = false; }
  }
  async function archive() {
    if (!confirm('Archive this environment? Its metadata and services will be preserved.')) return;
    pending = true; message = ''; success = '';
    try { await mutate(base, 'DELETE', data.session.csrf_token); await goto(`/projects/${data.project.id}/environments`, { invalidateAll: true }); }
    catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to archive environment.'; }
    finally { pending = false; }
  }
</script>
<svelte:head><title>{data.environment.name} · LAVA</title></svelte:head>
<a class="back-link" href={`/projects/${data.project.id}/environments`}>← Environments</a>
<div class="page-heading"><div><p class="eyebrow">ENVIRONMENT</p><h1>{data.environment.name}</h1><p class="muted">{data.environment.description || data.environment.slug}</p></div><span class="badge">{data.environment.lifecycle_status}</span></div>
{#if message}<p role="alert" class="notice">{message}</p>{/if}
{#if success}<p role="status" class="success">{success}</p>{/if}
<section class="panel"><h2>Configuration overview</h2><p>Slug: <strong>{data.environment.slug}</strong></p><p class="muted">This environment stores desired configuration metadata. It does not deploy resources.</p></section>
<section class="panel" aria-labelledby="environment-services-title"><h2 id="environment-services-title">Associated services</h2>
  {#if data.services.length === 0}<p class="muted">No services are associated with this environment.</p>
  {:else}<ul class="resource-grid">{#each data.services as service}<li><a class="resource-card" href={`/projects/${data.project.id}/services/${service.id}`}><h3>{service.name}</h3><p>{service.service_type} · {service.desired_state}</p><span class="fine-print">View configuration →</span></a></li>{/each}</ul>{/if}
</section>
{#if canConfigure}<section class="panel form-panel" aria-labelledby="environment-settings-title"><h2 id="environment-settings-title">Environment settings</h2><form onsubmit={save}><fieldset disabled={pending}>
  <label for="edit-environment-name">Name</label><input id="edit-environment-name" bind:value={name} required maxlength="100" />
  <label for="edit-environment-description">Description</label><textarea id="edit-environment-description" bind:value={description} maxlength="2000" rows="3"></textarea>
  <div class="actions"><button type="submit">{pending ? 'Saving…' : 'Save environment'}</button><button type="button" class="secondary danger" onclick={archive}>Archive environment</button></div>
</fieldset></form></section>{/if}
