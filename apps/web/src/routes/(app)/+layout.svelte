<script lang="ts">
  let { data, children } = $props();
</script>

<div class="app-shell">
  <header class="app-header">
    <a href="/projects" class="brand" aria-label="LAVA projects">LAVA<span class="brand-dot">.</span></a>
    <nav aria-label="Main navigation"><a href="/projects">Projects</a><a href="/invitations">Invitations</a><a href="/sessions">Account</a></nav>
    <span class="user-name">{data.session.user.name}</span>
  </header>
  <main id="main-content" class="main-content">{@render children()}</main>
  <footer class="app-footer">LAVA control plane · Service configuration is metadata; no customer workloads run in this release.</footer>
</div>
