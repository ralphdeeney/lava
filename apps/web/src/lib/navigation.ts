const uuid = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}';
const destinations = new RegExp(`^/projects(?:/new|/${uuid}(?:/services/(?:new|${uuid}))?)?$`);

export function safeNext(value: string | null): string {
  if (value === '/sessions' || value === '/' || (value && destinations.test(value))) {
    return value;
  }
  return '/projects';
}
