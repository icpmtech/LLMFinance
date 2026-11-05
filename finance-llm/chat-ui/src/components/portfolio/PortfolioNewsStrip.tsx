import { ExternalLink, ThumbsDown, ThumbsUp, Minus } from "lucide-react";
import type { PortfolioNewsItem } from "../../portfolioApi";

interface PortfolioNewsStripProps {
  news: PortfolioNewsItem[];
}

function sentimentIcon(sentiment?: string) {
  const s = (sentiment ?? "").toLowerCase();
  if (s.includes("posit")) return <ThumbsUp className="h-3 w-3 text-emerald-400" />;
  if (s.includes("negat")) return <ThumbsDown className="h-3 w-3 text-rose-400" />;
  return <Minus className="h-3 w-3 text-slate-500" />;
}

export function PortfolioNewsStrip({ news }: PortfolioNewsStripProps) {
  if (!news.length) {
    return <p className="text-sm text-slate-500">Sem notícias recentes.</p>;
  }

  return (
    <div className="space-y-3">
      {news.map((item) => (
        <a
          key={item.id}
          href={item.url || "#"}
          target="_blank"
          rel="noopener noreferrer"
          className="group block rounded-md border border-slate-800/60 bg-slate-950/40 p-3 hover:border-slate-700 transition"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                {sentimentIcon(item.sentiment)}
                <span className="text-xs font-medium text-slate-400">
                  {item.publisher || "Fonte desconhecida"}
                </span>
                {item.ticker && (
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                    {item.ticker}
                  </span>
                )}
              </div>
              <h3 className="mt-1 text-sm font-medium text-slate-200 group-hover:text-white line-clamp-2">
                {item.title}
              </h3>
              {item.summary && (
                <p className="mt-1 text-xs text-slate-500 line-clamp-2">{item.summary}</p>
              )}
            </div>
            <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-600 group-hover:text-slate-400" />
          </div>
          {item.published && (
            <div className="mt-2 text-[10px] text-slate-600">
              {new Date(item.published).toLocaleString(undefined, {
                day: "2-digit",
                month: "short",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </div>
          )}
        </a>
      ))}
    </div>
  );
}
