interface BadgeProps {
  label: string;
  className?: string;
}

export function StatusBadge({ label }: { label: string }) {
  const styles: Record<string, string> = {
    pending: "bg-amber-100 text-amber-800",
    queued: "bg-gray-100 text-gray-700",
    parsing: "bg-blue-100 text-blue-800",
    searching: "bg-blue-100 text-blue-800",
    enriching: "bg-blue-100 text-blue-800",
    icp_scoring: "bg-purple-100 text-purple-800",
    generating_signals: "bg-purple-100 text-purple-800",
    syncing_crm: "bg-indigo-100 text-indigo-800",
    completed: "bg-green-100 text-green-800",
    enriched: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
    retrying: "bg-amber-100 text-amber-800",
    synced: "bg-green-100 text-green-800",
    syncing: "bg-blue-100 text-blue-800",
    skipped_duplicate: "bg-gray-100 text-gray-700",
  };

  return (
    <Badge
      label={label}
      className={styles[label] ?? "bg-gray-100 text-gray-800"}
    />
  );
}

export function ConfidenceBadge({ confidence }: { confidence: string }) {
  const styles: Record<string, string> = {
    high: "bg-green-100 text-green-800",
    medium: "bg-yellow-100 text-yellow-800",
    low: "bg-gray-100 text-gray-700",
  };

  return (
    <Badge
      label={confidence}
      className={styles[confidence] ?? "bg-gray-100 text-gray-800"}
    />
  );
}

function Badge({ label, className = "" }: BadgeProps) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium capitalize ${className}`}
    >
      {label.replace(/_/g, " ")}
    </span>
  );
}
