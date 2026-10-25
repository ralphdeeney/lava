<script lang="ts">
  import { invalidateAll } from '$app/navigation';
  import { mutate } from '$lib/client';
  import type { ProjectRole } from '$lib/models';
  let { data } = $props();
  let pending = $state(false);
  let message = $state('');
  let success = $state('');
  let username = $state('');
  let role = $state<ProjectRole>('developer');
  const canManage = $derived(data.project.my_role === 'owner' || data.project.my_role === 'admin');
  const assignable = ['admin', 'developer', 'viewer'];
  const base = $derived(`/projects/${data.project.id}`);
  async function invite(event: SubmitEvent) {
    event.preventDefault(); pending = true; message = ''; success = '';
    try {
      await mutate(`${base}/invitations`, 'POST', data.session.csrf_token, { username: username.trim(), role });
      username = ''; success = 'Invitation created. The user can accept it from their Invitations page.';
      await invalidateAll();
    } catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to invite member.'; }
    finally { pending = false; }
  }
  async function updateRole(event: SubmitEvent, membershipId: string) {
    event.preventDefault(); pending = true; message = ''; success = '';
    const selected = String(new FormData(event.currentTarget as HTMLFormElement).get('role'));
    try { await mutate(`${base}/members/${membershipId}`, 'PATCH', data.session.csrf_token, { role: selected }); success = 'Role updated.'; await invalidateAll(); }
    catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to update role.'; }
    finally { pending = false; }
  }
  async function revokeMember(membershipId: string) {
    if (!confirm('Revoke this member’s project access?')) return;
    pending = true; message = ''; success = '';
    try { await mutate(`${base}/members/${membershipId}`, 'DELETE', data.session.csrf_token); success = 'Access revoked.'; await invalidateAll(); }
    catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to revoke access.'; }
    finally { pending = false; }
  }
  async function revokeInvite(invitationId: string) {
    pending = true; message = ''; success = '';
    try { await mutate(`${base}/invitations/${invitationId}`, 'DELETE', data.session.csrf_token); success = 'Invitation revoked.'; await invalidateAll(); }
    catch (problem) { message = problem instanceof Error ? problem.message : 'Unable to revoke invitation.'; }
    finally { pending = false; }
  }
</script>
<svelte:head><title>Members · {data.project.name} · LAVA</title></svelte:head>
<a class="back-link" href={`/projects/${data.project.id}`}>← {data.project.name}</a>
<div class="page-heading"><div><p class="eyebrow">PROJECT ACCESS</p><h1>Members</h1><p class="muted">People with access to {data.project.name}.</p></div></div>
{#if message}<p role="alert" class="notice">{message}</p>{/if}
{#if success}<p role="status" class="success">{success}</p>{/if}
<section class="panel" aria-labelledby="members-title">
  <h2 id="members-title">Current members</h2>
  {#if data.members.length === 0}<p class="muted">No active members.</p>{:else}
    <ul class="resource-grid">
      {#each data.members as member}
        <li class="resource-card">
          <h3>{member.user_name}</h3><p class="muted">{member.role} · {member.status}</p>
          {#if canManage && member.status === 'active' && member.role !== 'owner'}
            <form onsubmit={(event) => updateRole(event, member.id)}>
              <label for={`role-${member.id}`}>Role for {member.user_name}</label>
              <select id={`role-${member.id}`} name="role" value={member.role} disabled={pending}>
                {#each assignable as option}<option value={option}>{option}</option>{/each}
              </select>
              <div class="actions"><button type="submit" disabled={pending}>Save role</button><button type="button" class="secondary danger" disabled={pending} onclick={() => revokeMember(member.id)}>Revoke access</button></div>
            </form>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>
{#if canManage && data.project.lifecycle_status === 'active'}
  <section class="panel form-panel" aria-labelledby="invite-title">
    <h2 id="invite-title">Invite member</h2><p class="muted">Invite an existing LAVA account. They will find it on their Invitations page.</p>
    <form onsubmit={invite}><fieldset disabled={pending}>
      <label for="invite-username">Username</label><input id="invite-username" autocomplete="off" bind:value={username} required maxlength="100" />
      <label for="invite-role">Role</label><select id="invite-role" bind:value={role}>{#each assignable as option}<option value={option}>{option}</option>{/each}</select>
      <div class="actions"><button type="submit">{pending ? 'Inviting…' : 'Invite member'}</button></div>
    </fieldset></form>
  </section>
  <section class="panel" aria-labelledby="pending-title"><h2 id="pending-title">Pending invitations</h2>
    {#if data.invitations.filter(invitation => invitation.status === 'pending').length === 0}<p class="muted">No pending invitations.</p>
    {:else}<ul class="resource-grid">{#each data.invitations.filter(invitation => invitation.status === 'pending') as invitation}
      <li class="resource-card"><h3>{invitation.invitee_name}</h3><p class="muted">{invitation.role} · Expires {new Date(invitation.expires_at).toLocaleDateString()}</p><button class="secondary danger" disabled={pending} onclick={() => revokeInvite(invitation.id)}>Revoke invitation</button></li>
    {/each}</ul>{/if}
  </section>
{/if}
