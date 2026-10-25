<script lang="ts">let { data } = $props();</script>
<svelte:head><title>Projects · LAVA</title></svelte:head>
<div class="page-heading"><div><p class="eyebrow">WORKSPACE</p><h1>Projects</h1><p class="muted">Your projects and their service configuration.</p></div><a class="button" href="/projects/new">Create project</a></div>
{#if data.projects.length === 0}
  <section class="empty-state"><h2>No projects yet</h2><p>Create a project to organize your services.</p><a href="/projects/new">Create your first project</a></section>
{:else}
  <ul class="resource-grid">
    {#each data.projects as project}
      <li><a class="resource-card" href={`/projects/${project.id}`}><span class="badge">{project.lifecycle_status}</span><h2>{project.name}</h2><p>{project.description || 'No description'}</p><span class="fine-print">Open project →</span></a></li>
    {/each}
  </ul>
{/if}
