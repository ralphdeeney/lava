<script lang="ts">
  let { data } = $props();
  const canConfigure = $derived(data.project.lifecycle_status === 'active' && ['owner', 'admin', 'developer'].includes(data.project.my_role));
</script>
<svelte:head><title>Environments · {data.project.name} · LAVA</title></svelte:head>
<a class="back-link" href={`/projects/${data.project.id}`}>← {data.project.name}</a>
<div class="page-heading"><div><p class="eyebrow">PROJECT CONFIGURATION</p><h1>Environments</h1><p class="muted">Isolated configuration metadata for {data.project.name}.</p></div>{#if canConfigure}<a class="button" href={`/projects/${data.project.id}/environments/new`}>Create environment</a>{/if}</div>
{#if data.environments.length === 0}<section class="empty-state"><h2>No environments yet</h2><p>Create development, staging, production, or a custom environment.</p>{#if canConfigure}<a href={`/projects/${data.project.id}/environments/new`}>Create environment</a>{/if}</section>
{:else}<ul class="resource-grid">{#each data.environments as environment}
  <li><a class="resource-card" href={`/projects/${data.project.id}/environments/${environment.id}`}><span class="badge">{environment.lifecycle_status}</span><h2>{environment.name}</h2><p>{environment.description || environment.slug}</p><span class="fine-print">View environment →</span></a></li>
{/each}</ul>{/if}
