/**
 * Ficha de um registo **LEI** (GLEIF).
 *
 * Vive num módulo próprio porque é usada em três sítios: na coluna lateral da
 * pesquisa (`pages/GleifPage.tsx`), na janela de uma região
 * (`GleifRegionWindow.tsx`) e na janela de um registo (`GleifRecordWindow.tsx`).
 */
import { Building2, Copy, ExternalLink, Map as MapIcon, X } from "lucide-react";
import { useState } from "react";
import {
  categoryLabel,
  corroborationLabel,
  shortDate,
  sourceLabel,
  statusLabel,
  type GleifLei,
} from "../../gleifApi";
import { countryFlag, countryName } from "../geo/world";

/** Endereço da ficha oficial do registo no LEI Search do GLEIF. */
export function gleifRecordUrl(lei: string): string {
  return `https://search.gleif.org/#/record/${encodeURIComponent(lei)}`;
}

/** Botão «copiar» com confirmação breve (usado no LEI). */
function CopyButton({ value, label = "Copiar" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(value).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1400);
        });
      }}
      title={`${label}: ${value}`}
      className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
    >
      <Copy size={10} />
      {copied ? "copiado" : label}
    </button>
  );
}

interface LeiDetailProps {
  record: GleifLei;
  /** Fechar a ficha (a janela/painel que a mostra decide o que fazer). */
  onClose: () => void;
  /** Levar o mapa a esta localização; em falta, o botão não aparece. */
  onOpenMap?: (filter: { country?: string; region?: string }) => void;
}

export default function LeiDetail({ record, onClose, onOpenMap }: LeiDetailProps) {
  const rows: [string, React.ReactNode][] = [
    ["LEI", <span className="font-mono">{record.lei}</span>],
    ["Estado da entidade", statusLabel(record.status)],
    ["Estado do registo", statusLabel(record.registration_status)],
    ["Jurisdição", record.jurisdiction || "—"],
    ["Categoria", categoryLabel(record.category)],
    [
      "Forma jurídica",
      record.legal_form ? `${record.legal_form}${record.legal_form_other ? ` (${record.legal_form_other})` : ""}` : "—",
    ],
    ["NIF de registo", record.registered_as || "—"],
    ["Registo em", record.registered_at || "—"],
    ["Validado como", record.validated_as || "—"],
    ["LOU emissor", <span className="font-mono">{record.managing_lou || "—"}</span>],
    ["Corroboração", corroborationLabel(record.corroboration_level)],
    ["Registo inicial", shortDate(record.initial_registration_date)],
    ["Última atualização", shortDate(record.last_update_date)],
    ["Próxima renovação", shortDate(record.next_renewal_date)],
    ["Criação da entidade", shortDate(record.creation_date)],
    ["BIC", record.bic || "—"],
    ["MIC", record.mic || "—"],
    ["OCID", record.ocid || "—"],
    ["QCC", record.qcc || "—"],
    ["Origem no IQ OS", sourceLabel(record.source)],
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start gap-2">
        <span className="text-2xl leading-none">{countryFlag(record.country)}</span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-foreground">{record.legal_name}</h2>
          <p className="text-[11px] text-muted-foreground">
            {[record.city, record.region_name || record.region, countryName(record.country)].filter(Boolean).join(" · ")}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          title="Fechar"
          className="rounded-full p-1 text-muted-foreground transition hover:bg-white/10"
        >
          <X size={13} />
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        <CopyButton value={record.lei} label="copiar LEI" />
        {onOpenMap && (
          <button
            type="button"
            onClick={() => onOpenMap({ country: record.country || undefined, region: record.region || undefined })}
            className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
          >
            <MapIcon size={10} />
            ver no mapa
          </button>
        )}
        <a
          href={gleifRecordUrl(record.lei)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
        >
          <ExternalLink size={10} />
          ficha no GLEIF
        </a>
      </div>

      {(record.address_lines?.length || record.postal_code) && (
        <div className="rounded-2xl glass-card px-3 py-2 text-[11px]">
          <p className="mb-1 flex items-center gap-1 text-muted-foreground">
            <Building2 size={11} /> Sede legal
          </p>
          <p className="text-foreground">
            {[...(record.address_lines || []), record.postal_code, record.city].filter(Boolean).join(", ")}
          </p>
        </div>
      )}

      {record.other_names && record.other_names.length > 0 && (
        <div className="rounded-2xl glass-card px-3 py-2 text-[11px]">
          <p className="mb-1 text-muted-foreground">Outros nomes</p>
          <ul className="list-inside list-disc text-foreground">
            {record.other_names.slice(0, 8).map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        </div>
      )}

      <dl className="rounded-2xl glass-card px-3 py-2 text-[11px]">
        {rows.map(([label, value]) => (
          <div key={label} className="grid grid-cols-[1fr_auto] items-baseline gap-3 py-0.5">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="text-right text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
