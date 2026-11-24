import type { Verdict } from '../types/api';
import { VERDICT_META } from '../utils/format';

interface VerdictBadgeProps {
  verdict: Verdict;
  compact?: boolean;
}

export function VerdictBadge({ verdict, compact = false }: VerdictBadgeProps) {
  const meta = VERDICT_META[verdict];

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap ${meta.badgeClass}`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${meta.dotClass}`} />
      <span>{compact ? meta.shortLabel : meta.label}</span>
    </span>
  );
}
