<script lang="ts">import { page } from '$app/state';</script>
<svelte:head><title>Request unavailable · LAVA</title></svelte:head>
<main class="error-shell" id="main-content">
  <p class="eyebrow">LAVA</p><h1>{page.status === 404 ? 'Resource not available' : 'Unable to complete this request'}</h1>
  <p class="muted">{page.status === 404 ? 'This resource does not exist or is not available to your account.' : 'Please try again. If your session has expired, log in again.'}</p>
  <div class="actions"><a class="button" href="/projects">Projects</a><a href="/login">Log in</a></div>
</main>
