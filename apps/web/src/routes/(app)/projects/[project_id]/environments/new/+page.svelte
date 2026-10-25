<script lang="ts">
  import { goto } from '$app/navigation';
  import { mutate } from '$lib/client';
  import type { Environment } from '$lib/models';
  let { data } = $props();
  let name = $state(''); let slug = $state(''); let description = $state(''); let pending = $state(false); let message = $state('');
  const canConfigure = $derived(data.project.lifecycle_status === 'active' && ['owner', 'admin', 'developer'].includes(data.project.my_role));
  async function create(event: SubmitEvent) {
    event.preventDefault(); pending = true; message = '';
    try {
      const created = await mutate<Environment>(`/projects/${data.project.id}/environments`, 'POST', data.session.csrf_token, { name, slug, description });
      await goto(`/projects/${data.project.id}/environments/${created.id}`, { invalidateAll: true });
    } catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to create environment.'; }
    finally { pending = false; }
  }
</script>
<svelte:head><title>Create environment · LAVA</title></svelte:head>
<a class="back-link" href={`/projects/${data.project.id}/environments`}>← Environments</a>
<div class="page-heading"><div><h1>Create environment</h1><p class="muted">Store configuration metadata for {data.project.name}. No resources are deployed.</p></div></div>
{#if message}<p role="alert" class="notice">{message}</p>{/if}
{#if canConfigure}<section class="panel form-panel"><form onsubmit={create}><fieldset disabled={pending}>
  <label for="environment-name">Name</label><input id="environment-name" bind:value={name} required maxlength="100" />
  <label for="environment-slug">Slug</label><input id="environment-slug" bind:value={slug} required maxlength="63" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" aria-describedby="slug-help" /><p id="slug-help" class="fine-print">Lowercase letters, numbers and hyphens.</p>
  <label for="environment-description">Description</label><textarea id="environment-description" bind:value={description} maxlength="2000" rows="3"></textarea>
  <div class="actions"><button type="submit">{pending ? 'Creating…' : 'Create environment'}</button></div>
</fieldset></form></section>{:else}<p role="alert" class="notice">Your project role cannot create environments.</p>{/if}
