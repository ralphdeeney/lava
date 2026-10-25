<script lang="ts">
  import { enhance } from '$app/forms';
  let { data, form } = $props(); let pending = $state(false);
  function handling() {
    pending = true;
    return async ({ update }: { update: () => Promise<void> }) => { pending = false; await update(); };
  }
</script>
<svelte:head><title>Sessions · LAVA</title></svelte:head>
<div class="page-heading"><div><p class="eyebrow">ACCOUNT</p><h1>Sessions</h1><p class="muted">Manage access for your account.</p></div></div>
{#if form?.message}<p role="alert" class="notice">{form.message}</p>{/if}
<section class="panel" aria-labelledby="current-session-title">
  <h2 id="current-session-title">Current session</h2>
  <dl class="details"><div><dt>User</dt><dd>{data.session.user.name}</dd></div><div><dt>Expires</dt><dd><time datetime={data.session.expires_at}>{new Date(data.session.expires_at).toISOString().replace('T', ' ').replace('.000Z', ' UTC')}</time></dd></div></dl>
  <form method="POST" action="?/logout" use:enhance={handling}><button disabled={pending}>Log out</button></form>
</section>
<section class="panel" aria-labelledby="all-sessions-title">
  <h2 id="all-sessions-title">All sessions</h2><p class="muted">Log out every active session, including this browser. You will need to log in again on each device.</p>
  <form method="POST" action="?/logoutAll" use:enhance={handling}><button class="secondary danger" disabled={pending}>Log out all sessions</button></form>
</section>
