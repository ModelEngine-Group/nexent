type Provider = { provider_name: string; provider_config_id: number | string };

export function ownedProviderId(items: unknown, name: string, previous: number | null): number | null {
  if (!Array.isArray(items)) throw new Error("Provider list must contain items");
  const matches = items.filter((item: Provider) =>
    item && [name, `${name}-updated`].includes(item.provider_name));
  if (matches.length > 1) throw new Error("Owned Provider name is ambiguous");
  if (!matches.length) return null;
  const id = Number(matches[0].provider_config_id);
  if (!Number.isSafeInteger(id) || id <= 0) throw new Error("Owned Provider ID is invalid");
  if (previous !== null && id !== previous) throw new Error("Owned Provider identity changed");
  return id;
}
