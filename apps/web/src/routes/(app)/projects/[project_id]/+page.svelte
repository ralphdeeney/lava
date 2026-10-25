<script lang="ts">
  import { goto, invalidateAll } from '$app/navigation';
  import { mutate } from '$lib/client';
  let { data } = $props();
  let name = $state(''); let description = $state(''); let pending = $state(false); let message = $state(''); let saved = $state(false);
  $effect(() => { name = data.project.name; description = data.project.description; });
  async function save(event: SubmitEvent) {
    event.preventDefault(); pending = true; message = ''; saved = false;
    try { await mutate(`/projects/${data.project.id}`, 'PATCH', data.session.csrf_token, { name, description }); await invalidateAll(); saved = true; }
    catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to save project.'; }
    finally { pending = false; }
  }
  async function archive() {
    if (!confirm('Archive this project and its services? This stops future configuration changes.')) return;
    pending = true; message = '';
    try { await mutate(`/projects/${data.project.id}`, 'DELETE', data.session.csrf_token); await goto('/projects', { invalidateAll: true }); }
    catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to archive project.'; }
    finally { pending = false; }
  }
</script>
<svelte:head><title>{data.project.name} · LAVA</title></svelte:head>
<a class="back-link" href="/projects">← Projects</a>
<div class="page-heading"><div><p class="eyebrow">PROJECT</p><h1>{data.project.name}</h1><p class="muted">{data.project.description || 'No description'}</p></div><span class="badge">{data.project.lifecycle_status}</span></div>
{#if message}<p role="alert" class="notice">{message}</p>{/if}
{#if saved}<p role="status" class="success">Project saved.</p>{/if}
<section aria-labelledby="services-title">
  <div class="section-heading"><h2 id="services-title">Services</h2>{#if data.project.lifecycle_status === 'active'}<a class="button" href={`/projects/${data.project.id}/services/new`}>Create service</a>{/if}</div>
  {#if data.services.length === 0}<div class="empty-state"><p>No services yet. Register a service to keep its configuration here.</p></div>
  {:else}<ul class="resource-grid">{#each data.services as service}<li><a class="resource-card" href={`/projects/${data.project.id}/services/${service.id}`}><span class="badge">{service.desired_state}</span><h3>{service.name}</h3><p>{service.service_type} · {service.resources.cpu} CPU · {service.resources.memory_mb} MiB</p><span class="fine-print">View configuration →</span></a></li>{/each}</ul>{/if}
</section>
<section class="panel form-panel" aria-labelledby="project-settings-title">
  <h2 id="project-settings-title">Project settings</h2>
  <form onsubmit={save}>
    <fieldset disabled={pending || data.project.lifecycle_status === 'archived'}>
      <label for="project-name">Project name</label><input id="project-name" bind:value={name} required maxlength="100" />
      <label for="project-description">Description</label><textarea id="project-description" bind:value={description} maxlength="2000" rows="3"></textarea>
      <div class="actions"><button type="submit">{pending ? 'Saving…' : 'Save project'}</button><button class="danger secondary" type="button" onclick={archive}>Archive project</button></div>
    </fieldset>
  </form>
</section>
