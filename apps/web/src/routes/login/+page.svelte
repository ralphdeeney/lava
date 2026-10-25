<script lang="ts">
  import { enhance } from '$app/forms';
  let { form } = $props();
  let pending = $state(false);
</script>

<svelte:head><title>Log in · LAVA</title></svelte:head>
<main class="login-shell" id="main-content">
  <section class="login-panel" aria-labelledby="login-title">
    <a href="/login" class="brand" aria-label="LAVA home">LAVA<span class="brand-dot">.</span></a>
    <p class="eyebrow">CONTROL PLANE</p>
    <h1 id="login-title">Log in</h1>
    <p class="muted">Use your provisioned account to manage projects and service configuration.</p>
    {#if form?.message}<p role="alert" class="notice">{form.message}</p>{/if}
    <form method="POST" use:enhance={() => {
      pending = true;
      return async ({ update }) => { pending = false; await update(); };
    }}>
      <label for="username">Username</label>
      <input id="username" name="username" autocomplete="username" required maxlength="100" />
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required maxlength="1024" />
      <button type="submit" disabled={pending}>{pending ? 'Logging in…' : 'Log in'}</button>
    </form>
    <p class="fine-print">Accounts are provisioned by your operator. Public registration and password recovery are not available in this release.</p>
  </section>
</main>
