export const leadKeys = {
  all: ["leads"] as const,
  detail: (id: string | number) => ["leads", String(id)] as const,
  stats: ["stats"] as const,
};
