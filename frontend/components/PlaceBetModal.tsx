"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import {
  KIND_LABEL,
  money,
  num,
  pct,
  usd,
} from "@/lib/format";
import type { Arb, ArbLeg } from "@/lib/types";

import { FlagChip, VenueChip, ZoneChip } from "./ui";

interface PlaceBetModalProps {
  arb: Arb;
  onClose: () => void;
  onSuccess: (message?: string) => void;
}

export function PlaceBetModal({ arb, onClose, onSuccess }: PlaceBetModalProps) {
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [note, setNote] = useState("");
  const [showOverrides, setShowOverrides] = useState(false);

  // Custom executed price & stake inputs if the user experienced slight slippage
  const [customPrices, setCustomPrices] = useState<string[]>(
    arb.legs.map((l) => l.price.toString())
  );
  const [customStakes, setCustomStakes] = useState<string[]>(
    arb.legs.map((l) => l.stake.toString())
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  const handlePlace = async () => {
    if (!confirmed) {
      setError("Please confirm the placement checklist before proceeding.");
      return;
    }

    setBusy(true);
    setError(null);

    try {
      const executed_prices = customPrices.map((p) => parseFloat(p) || 0);
      const executed_stakes = customStakes.map((s) => parseFloat(s) || 0);

      const res = await api.placeBet(arb.id, {
        confirmed: true,
        executed_prices: showOverrides ? executed_prices : undefined,
        executed_stakes: showOverrides ? executed_stakes : undefined,
        note: note.trim() || undefined,
        retire: true,
      });

      setSuccess(true);
      setTimeout(() => {
        onSuccess(res.message);
      }, 1000);
    } catch (err: any) {
      setError(err?.message || "Failed to place bet. Please try again.");
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <div
        className="absolute inset-0 transition-opacity"
        style={{ background: "rgba(0,0,0,0.65)", backdropFilter: "blur(2px)" }}
        onClick={() => !busy && onClose()}
      />

      <div
        className="relative w-full max-w-2xl rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]"
        style={{
          background: "var(--bg)",
          border: "1px solid var(--border)",
        }}
      >
        {/* Header */}
        <div
          className="px-6 py-4 border-b flex items-start justify-between gap-4"
          style={{ background: "var(--bg-elevated)", borderColor: "var(--border)" }}
        >
          <div>
            <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
              <span className="chip chip-accent">{KIND_LABEL[arb.kind]}</span>
              {arb.venues.map((v) => (
                <VenueChip key={v} venue={v} />
              ))}
              <ZoneChip zone={arb.zone} short />
            </div>
            <h2 id="modal-title" className="text-base font-semibold leading-tight">
              Confirm Bet Placement: {arb.title}
            </h2>
          </div>
          <button
            className="btn btn-sm shrink-0"
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto flex flex-col gap-5">
          {success ? (
            <div
              className="p-6 rounded-xl text-center flex flex-col items-center gap-3"
              style={{ background: "var(--positive-soft)", border: "1px solid var(--positive)" }}
            >
              <div
                className="w-12 h-12 rounded-full flex items-center justify-center text-2xl"
                style={{ background: "var(--positive)", color: "#fff" }}
              >
                ✓
              </div>
              <h3 className="text-base font-semibold" style={{ color: "var(--positive)" }}>
                Bet Placed &amp; Recorded!
              </h3>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                The opportunity has been logged in your Positions ledger. Refreshing live opportunities now…
              </p>
            </div>
          ) : (
            <>
              {/* Summary Stats */}
              <div className="grid grid-cols-3 gap-3">
                <div className="card p-3 text-center">
                  <div className="label">Total Stake</div>
                  <div className="mono text-base font-semibold mt-1">
                    {money(arb.total_stake, arb.currency)}
                  </div>
                </div>
                <div className="card p-3 text-center">
                  <div className="label">Guaranteed Profit</div>
                  <div className="mono text-base font-semibold num-positive mt-1">
                    {money(arb.worst_case_profit, arb.currency)}
                  </div>
                </div>
                <div className="card p-3 text-center">
                  <div className="label">Net Margin</div>
                  <div className="mono text-base font-semibold mt-1">
                    {pct(arb.net_margin)}
                  </div>
                </div>
              </div>

              {/* Legs Review */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="label">Order Legs ({arb.legs.length})</div>
                  <button
                    type="button"
                    className="text-xs hover:underline"
                    style={{ color: "var(--accent)" }}
                    onClick={() => setShowOverrides((o) => !o)}
                  >
                    {showOverrides ? "Hide price adjustments" : "Adjust executed prices/stakes"}
                  </button>
                </div>

                <div className="flex flex-col gap-2.5">
                  {arb.legs.map((leg: ArbLeg, idx: number) => (
                    <div
                      key={idx}
                      className="p-3 rounded-lg border flex flex-col gap-2"
                      style={{
                        background: "var(--bg-sunken)",
                        borderColor: "var(--border)",
                      }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="chip text-xs font-semibold uppercase">
                            {leg.side}
                          </span>
                          <span className="text-sm font-medium truncate">
                            {leg.outcome}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <VenueChip venue={leg.venue} />
                          {leg.url && (
                            <a
                              href={leg.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="btn btn-sm"
                              title={`Open market on ${leg.venue}`}
                            >
                              Open Market ↗
                            </a>
                          )}
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs pt-1 border-t" style={{ borderColor: "var(--border)" }}>
                        <div className="mono" style={{ color: "var(--text-muted)" }}>
                          Target Price: <span className="font-semibold text-white">{leg.price.toFixed(4)}</span> ({leg.decimal_odds.toFixed(2)}x)
                        </div>
                        <div className="mono" style={{ color: "var(--text-muted)" }}>
                          Stake: <span className="font-semibold text-white">{money(leg.stake, arb.currency)}</span> · {num(leg.contracts, 0)} contracts
                        </div>
                      </div>

                      {showOverrides && (
                        <div className="grid grid-cols-2 gap-2 pt-2 mt-1 border-t" style={{ borderColor: "var(--border)" }}>
                          <div>
                            <label className="text-[11px] block mb-1" style={{ color: "var(--text-faint)" }}>
                              Actual Executed Price
                            </label>
                            <input
                              type="number"
                              step="0.0001"
                              className="input text-xs w-full"
                              value={customPrices[idx] || ""}
                              onChange={(e) => {
                                const copy = [...customPrices];
                                copy[idx] = e.target.value;
                                setCustomPrices(copy);
                              }}
                            />
                          </div>
                          <div>
                            <label className="text-[11px] block mb-1" style={{ color: "var(--text-faint)" }}>
                              Actual Executed Stake
                            </label>
                            <input
                              type="number"
                              step="0.01"
                              className="input text-xs w-full"
                              value={customStakes[idx] || ""}
                              onChange={(e) => {
                                const copy = [...customStakes];
                                copy[idx] = e.target.value;
                                setCustomStakes(copy);
                              }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Optional Note */}
              <div>
                <label htmlFor="placement-note" className="label block mb-1">
                  Reference Note (Optional)
                </label>
                <input
                  id="placement-note"
                  type="text"
                  placeholder="e.g. Kalshi order #9021, Smarkets session confirmation"
                  className="input w-full text-xs"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  disabled={busy}
                />
              </div>

              {/* Mandatory Confirmation Box */}
              <div
                className="p-3.5 rounded-lg border flex items-start gap-3 cursor-pointer select-none"
                style={{
                  background: confirmed ? "var(--accent-soft)" : "var(--bg-sunken)",
                  borderColor: confirmed ? "var(--accent)" : "var(--border)",
                }}
                onClick={() => !busy && setConfirmed(!confirmed)}
              >
                <input
                  type="checkbox"
                  id="confirm-checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                  disabled={busy}
                  className="mt-0.5"
                />
                <label htmlFor="confirm-checkbox" className="text-xs leading-relaxed cursor-pointer">
                  <span className="font-semibold text-white block">
                    I confirm that I have reviewed and verified all {arb.legs.length} legs.
                  </span>
                  <span style={{ color: "var(--text-muted)" }}>
                    I understand that placing this trade will record the position in my ledger and refresh the active opportunities list.
                  </span>
                </label>
              </div>

              {error && (
                <div
                  className="p-3 rounded-lg text-xs"
                  style={{ background: "var(--danger-soft)", color: "var(--danger)" }}
                >
                  {error}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer Actions */}
        {!success && (
          <div
            className="px-6 py-4 border-t flex items-center justify-between gap-3"
            style={{ background: "var(--bg-elevated)", borderColor: "var(--border)" }}
          >
            <button
              type="button"
              className="btn btn-sm"
              onClick={onClose}
              disabled={busy}
            >
              Cancel
            </button>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={handlePlace}
                disabled={busy || !confirmed}
                style={{
                  opacity: confirmed && !busy ? 1 : 0.5,
                  minWidth: 140,
                }}
              >
                {busy ? "Placing..." : "Confirm & Place"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
