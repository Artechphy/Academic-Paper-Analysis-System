import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';
import type { Verdict } from '../types/api';
import { VERDICT_META } from '../utils/format';

interface VerdictBadgeProps {
  verdict: Verdict;
  compact?: boolean;
}

export function VerdictBadge({ verdict, compact = false }: VerdictBadgeProps) {
  const meta = VERDICT_META[verdict];
  const Icon =
    verdict === 'pass' ? CheckCircle2 : verdict === 'fail' ? XCircle : AlertTriangle;

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${meta.badgeClass}`}
    >
      <Icon className="h-3.5 w-3.5 shrink-0" />
      <span>{compact ? meta.shortLabel : meta.label}</span>
    </span>
  );
}
