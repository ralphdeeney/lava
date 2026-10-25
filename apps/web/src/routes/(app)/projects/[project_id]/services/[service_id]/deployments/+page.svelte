<script lang="ts">
  let { data } = $props();
  type Deployment = { id: string; source_commit_sha: string; status: string; environment_id: string; created_at: string; failure_message?: string | null };
</script>
<svelte:head><title>Deployments · LAVA</title></svelte:head>
<a class="back-link" href={`/projects/${data.project.id}/services/${data.service.id}`}>← {data.service.name}</a>
<div class="page-heading"><div><p class="eyebrow">DEPLOYMENT HISTORY</p><h1>{data.service.name}</h1></div></div>
<section class="panel"><h2>Deployments</h2>
  {#if !data.deployments.length}<p class="muted">No deployment metadata has been recorded.</p>{:else}
    <ul class="resource-list">{#each data.deployments as deployment}<li class="resource-card"><div><strong>{deployment.source_commit_sha}</strong><p class="muted">{deployment.status} · {new Date(deployment.created_at).toLocaleString()}</p>{#if deployment.failure_message}<p role="alert">{deployment.failure_message}</p>{/if}</div></li>{/each}</ul>
  {/if}
</section>
