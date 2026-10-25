<script lang="ts">
  import { goto } from '$app/navigation';
  import { mutate } from '$lib/client';
  import type { Project } from '$lib/models';
  let { data } = $props();
  let name = $state(''); let description = $state(''); let pending = $state(false); let message = $state('');
  async function submit(event: SubmitEvent) {
    event.preventDefault(); pending = true; message = '';
    try {
      const project = await mutate<Project>('/projects', 'POST', data.session.csrf_token, { name, description });
      await goto(`/projects/${project.id}`, { invalidateAll: true });
    } catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to create project.'; }
    finally { pending = false; }
  }
</script>
<svelte:head><title>Create project · LAVA</title></svelte:head>
<a class="back-link" href="/projects">← Projects</a>
<div class="page-heading"><div><h1>Create project</h1><p class="muted">Give this workspace a clear name.</p></div></div>
<section class="panel form-panel">
  {#if message}<p role="alert" class="notice">{message}</p>{/if}
  <form onsubmit={submit}>
    <label for="project-name">Project name</label><input id="project-name" bind:value={name} required maxlength="100" />
    <label for="project-description">Description</label><textarea id="project-description" bind:value={description} maxlength="2000" rows="4"></textarea>
    <div class="actions"><button disabled={pending} type="submit">{pending ? 'Creating…' : 'Create project'}</button><a href="/projects">Cancel</a></div>
  </form>
</section>
