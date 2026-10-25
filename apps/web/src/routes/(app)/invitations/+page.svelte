<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import { mutate } from '$lib/client';
  let { data } = $props();
  let pending = $state(false); let message = $state(''); let success = $state('');
  async function decide(id: string, decision: 'accept' | 'decline') {
    pending = true; message = ''; success = '';
    try {
      await mutate(`/invitations/${id}/${decision}`, 'POST', data.session.csrf_token, {});
      success = decision === 'accept' ? 'Invitation accepted.' : 'Invitation declined.';
      await invalidateAll();
    } catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to respond to invitation.'; }
    finally { pending = false; }
  }
</script>
<svelte:head><title>Invitations · LAVA</title></svelte:head>
<div class="page-heading"><div><p class="eyebrow">COLLABORATION</p><h1>Invitations</h1><p class="muted">Project invitations sent to your account.</p></div></div>
{#if message}<p role="alert" class="notice">{message}</p>{/if}
{#if success}<p role="status" class="success">{success}</p>{/if}
{#if data.invitations.length === 0}<section class="empty-state"><h2>No pending invitations</h2><p>When a project owner invites you, it will appear here.</p></section>
{:else}<ul class="resource-grid">{#each data.invitations as invitation}
  <li class="resource-card"><h2>{invitation.project_name ?? 'Project invitation'}</h2><p class="muted">Role: {invitation.role} · Expires {new Date(invitation.expires_at).toLocaleDateString()}</p><div class="actions"><button disabled={pending} onclick={() => decide(invitation.id, 'accept')}>Accept invitation</button><button class="secondary" disabled={pending} onclick={() => decide(invitation.id, 'decline')}>Decline invitation</button></div></li>
{/each}</ul>{/if}
