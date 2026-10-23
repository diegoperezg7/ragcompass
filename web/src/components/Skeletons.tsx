import { Skeleton } from "./ui";

export function DashboardSkeleton() {
  return (
    <div className="dashboard skeleton-dashboard" aria-hidden>
      <div className="pipeline">
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="pipe-step">
            <Skeleton h={12} w="40%" />
            <Skeleton h={18} w="70%" />
          </div>
        ))}
      </div>
      <div className="grid overview">
        <div className="panel">
          <Skeleton h={140} w={140} r={70} />
        </div>
        <div className="kpis">
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="kpi">
              <Skeleton h={12} w="50%" />
              <Skeleton h={26} w="70%" />
            </div>
          ))}
        </div>
      </div>
      <div className="grid two">
        <div className="panel">
          <Skeleton h={260} />
        </div>
        <div className="panel">
          <Skeleton h={260} />
        </div>
      </div>
    </div>
  );
}

export function TextSkeleton({ lines = 14 }: { lines?: number }) {
  return (
    <div className="text-skeleton" aria-hidden>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} h={12} w={`${55 + ((i * 37) % 45)}%`} />
      ))}
    </div>
  );
}
