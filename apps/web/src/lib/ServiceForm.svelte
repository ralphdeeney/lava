<script lang="ts">
  import type { Service } from '$lib/models';
  type Configuration = { name: string; service_type: Service['service_type']; desired_state: 'stopped' | 'running'; resources: { cpu: number; memory_mb: number } };
  let { initial, pending = false, disabled = false, submitLabel, onsubmit }:
    { initial?: Service; pending?: boolean; disabled?: boolean; submitLabel: string; onsubmit: (value: Configuration) => Promise<void> } = $props();
  let name = $state(''); let serviceType = $state<Service['service_type']>('web'); let desiredState = $state<'stopped' | 'running'>('stopped');
  let cpu = $state<number | undefined>(1); let memory = $state<number | undefined>(512);
  $effect(() => {
    if (initial) { name = initial.name; serviceType = initial.service_type; desiredState = initial.desired_state === 'running' ? 'running' : 'stopped'; cpu = initial.resources.cpu; memory = initial.resources.memory_mb; }
  });
  async function submit(event: SubmitEvent) {
    event.preventDefault();
    await onsubmit({ name, service_type: serviceType, desired_state: desiredState, resources: { cpu: Number(cpu), memory_mb: Number(memory) } });
  }
</script>
<form onsubmit={submit}>
  <fieldset disabled={pending || disabled}>
    <label for="service-name">Service name</label><input id="service-name" bind:value={name} required maxlength="100" />
    <div class="form-grid">
      <div><label for="service-type">Service type</label><select id="service-type" bind:value={serviceType}><option value="web">Web</option><option value="api">API</option><option value="worker">Worker</option><option value="database">Database</option></select></div>
      <div><label for="desired-state">Desired state</label><select id="desired-state" bind:value={desiredState}><option value="stopped">Stopped</option><option value="running">Running</option></select></div>
      <div><label for="cpu">CPU cores</label><input id="cpu" type="number" min="0.01" max="16" step="0.01" bind:value={cpu} required /></div>
      <div><label for="memory">Memory (MiB)</label><input id="memory" type="number" min="64" max="65536" step="1" bind:value={memory} required /></div>
    </div>
    <p class="fine-print">Desired state and resource limits describe requested configuration only. They do not start a container.</p>
    <button type="submit">{pending ? 'Saving…' : submitLabel}</button>
  </fieldset>
</form>
