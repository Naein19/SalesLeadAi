interface ScoreBarProps {
  score: number | null;
}

export function scoreColor(score: number | null): string {
  if (score === null) return "bg-gray-300";
  if (score < 40) return "bg-red-500";
  if (score <= 70) return "bg-yellow-400";
  return "bg-green-500";
}

export default function ScoreBar({ score }: ScoreBarProps) {
  const value = score ?? 0;
  const width = score === null ? 0 : Math.min(100, Math.max(0, value));

  return (
    <div className="flex min-w-[120px] items-center gap-2">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-200">
        <div
          className={`h-full rounded-full transition-all ${scoreColor(score)}`}
          style={{ width: `${width}%` }}
        />
      </div>
      <span className="w-8 text-right text-xs text-gray-600">
        {score === null ? "—" : score}
      </span>
    </div>
  );
}
