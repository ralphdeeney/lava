<script lang="ts">
  import type { Environment, Service } from '$lib/models';
  export type Configuration = { name: string; service_type: Service['service_type']; desired_state: 'stopped' | 'running'; resources: { cpu: number; memory_mb: number }; environment_id?: string | null; build_method: NonNullable<Service['build_method']>; start_command: string; deployment_branch: string; desired_replicas: number };
  let { initial, environments = [], pending = false, disabled = false, submitLabel, onsubmit }:
    { initial?: Service; environments?: Environment[]; pending?: boolean; disabled?: boolean; submitLabel: string; onsubmit: (value: Configuration) => Promise<void> } = $props();
  let name = $state(''); let serviceType = $state<Service['service_type']>('web'); let desiredState = $state<'stopped' | 'running'>('stopped');
  let cpu = $state<number | undefined>(1); let memory = $state<number | undefined>(512);
  let environmentId = $state(''); let buildMethod = $state<NonNullable<Service['build_method']>>('railpack');
  let startCommand = $state(''); let deploymentBranch = $state('main'); let desiredReplicas = $state<number | undefined>(1);
  $effect(() => {
    if (initial) { name = initial.name; serviceType = initial.service_type; desiredState = initial.desired_state === 'running' ? 'running' : 'stopped'; cpu = initial.resources.cpu; memory = initial.resources.memory_mb; environmentId = initial.environment_id ?? ''; buildMethod = initial.build_method ?? 'railpack'; startCommand = initial.start_command ?? ''; deploymentBranch = initial.deployment_branch ?? 'main'; desiredReplicas = initial.desired_replicas ?? 1; }
  });
  async function submit(event: SubmitEvent) {
    event.preventDefault();
    await onsubmit({ name, service_type: serviceType, desired_state: desiredState, resources: { cpu: Number(cpu), memory_mb: Number(memory) }, ...(environmentId ? { environment_id: environmentId } : initial ? { environment_id: null } : {}), build_method: buildMethod, start_command: startCommand, deployment_branch: deploymentBranch, desired_replicas: Number(desiredReplicas) });
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
      <div><label for="service-environment">Associated environment</label><select id="service-environment" bind:value={environmentId}><option value="">No environment</option>{#each environments.filter(environment => environment.lifecycle_status === 'active' || environment.id === initial?.environment_id) as environment}<option value={environment.id}>{environment.name}{environment.lifecycle_status === 'archived' ? ' (archived)' : ''}</option>{/each}</select></div>
      <div><label for="build-method">Build method</label><select id="build-method" bind:value={buildMethod}><option value="railpack">Railpack</option><option value="dockerfile">Dockerfile</option><option value="image">Prebuilt image</option></select></div>
      <div><label for="deployment-branch">Deployment branch</label><input id="deployment-branch" bind:value={deploymentBranch} required maxlength="200" /></div>
      <div><label for="desired-replicas">Desired replicas</label><input id="desired-replicas" type="number" min="0" max="10" step="1" bind:value={desiredReplicas} required /></div>
    </div>
    <label for="start-command">Start command</label><input id="start-command" bind:value={startCommand} maxlength="500" aria-describedby="start-command-help" /><p id="start-command-help" class="fine-print">Optional command metadata. LAVA will not execute it in this slice. Do not include passwords or other secrets.</p>
    <p class="fine-print">Desired state and resource limits describe requested configuration only. They do not start a container.</p>
    <button type="submit">{pending ? 'Saving…' : submitLabel}</button>
  </fieldset>
</form>
