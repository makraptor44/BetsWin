"use client";

import { useCallback, useEffect, useState } from "react";

import { Card, EmptyState, ErrorState, Skeleton, Stat, VenueChip, ZoneChip } from "@/components/ui";
import { api } from "@/lib/api";
import {
  KIND_LABEL,
  money,
  num,
  pct,
  signedMoney,
  usd,
} from "@/lib/format";
import type { PositionItem, PositionsResponse, UnwindQuoteResponse } from "@/lib/types";

export default function PositionsPage() {
  const [data, setData] = useState<PositionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"all" | "open" | "settled">("all");
  const [toast, setToast] = useState<string | null>(null);

  // Modals state
  const [resolvingItem, setResolvingItem] = useState<PositionItem | null>(null);
  const [unwindingItem, setUnwindingItem] = useState<PositionItem | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.positions();
      setData(res);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load positions ledger.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 5000);
  };

  const positions = data?.positions || [];
  const filtered = positions.filter((p) => {
    if (tab === "open") return !p.settled;
    if (tab === "settled") return p.settled;
    return true;
  });

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Positions &amp; Placed Bets</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--text-muted)" }}>
            Manage active trades: hold until event resolution or sell back early at live market bids.
          </p>
        </div>
        <button className="btn btn-sm" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "↻ Refresh Ledger"}
        </button>
      </header>

      {toast && (
        <div
          className="p-3.5 rounded-lg text-xs font-medium flex items-center justify-between shadow-md transition-all"
          style={{ background: "var(--positive)", color: "#fff" }}
        >
          <div className="flex items-center gap-2">
            <span className="text-sm">✓</span>
            <span>{toast}</span>
          </div>
          <button
            type="button"
            className="hover:opacity-75 font-bold px-2 py-0.5"
            onClick={() => setToast(null)}
          >
            ✕
          </button>
        </div>
      )}

      {error && <ErrorState message={error} onRetry={load} />}
      {loading && !data && <Skeleton rows={6} />}

      {data && (
        <>
          {/* Summary Stats */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat
              label="Active Placed Trades"
              value={positions.filter((p) => !p.settled).length}
              sub={`${positions.length} total logged`}
            />
            <Stat
              label="Locked Active Stake"
              value={usd(data.total_active_stake)}
              sub="across open positions"
            />
            <Stat
              label="Expected Profit"
              value={usd(data.total_expected_profit)}
              sub="guaranteed minimum"
              tone={data.total_expected_profit > 0 ? "positive" : undefined}
            />
            <Stat
              label="Realised P&L"
              value={usd(data.total_realised_pnl)}
              sub={`${positions.filter((p) => p.settled).length} settled trades`}
              tone={data.total_realised_pnl >= 0 ? "positive" : "danger"}
            />
          </div>

          {/* Filter Tabs */}
          <div className="flex items-center gap-2 border-b pb-2" style={{ borderColor: "var(--border)" }}>
            <button
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                tab === "all" ? "btn-primary" : "btn"
              }`}
              onClick={() => setTab("all")}
            >
              All ({positions.length})
            </button>
            <button
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                tab === "open" ? "btn-primary" : "btn"
              }`}
              onClick={() => setTab("open")}
            >
              Open Active ({positions.filter((p) => !p.settled).length})
            </button>
            <button
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                tab === "settled" ? "btn-primary" : "btn"
              }`}
              onClick={() => setTab("settled")}
            >
              Settled ({positions.filter((p) => p.settled).length})
            </button>
          </div>

          {/* Positions List */}
          {filtered.length === 0 ? (
            <Card>
              <EmptyState
                title="No positions found"
                body={
                  tab === "all"
                    ? "You have not placed or recorded any bets yet. Select an opportunity from the live scanner and click 'Place Bet'."
                    : `No ${tab} positions in this view.`
                }
              />
            </Card>
          ) : (
            <div className="flex flex-col gap-4">
              {filtered.map((pos) => (
                <Card key={pos.id} className="p-5 flex flex-col gap-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
                        <span className="chip chip-accent">{KIND_LABEL[pos.kind] || pos.kind}</span>
                        {pos.venues.map((v) => (
                          <VenueChip key={v} venue={v} />
                        ))}
                        <ZoneChip zone={pos.zone} short />
                        {pos.settled ? (
                          <span className="chip chip-positive">
                            ✓ Settled ({pos.settlement_type === "sell_back_early" ? "Sold Back" : "Resolution"})
                          </span>
                        ) : (
                          <span className="chip" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
                            ● Active Open
                          </span>
                        )}
                      </div>
                      <h3 className="text-base font-semibold">{pos.title}</h3>
                      <div className="text-xs mt-1" style={{ color: "var(--text-faint)" }}>
                        Placed: {new Date(pos.detected_at).toLocaleString()} · ID #{pos.id}
                      </div>
                    </div>

                    <div className="flex items-center gap-3 text-right">
                      <div>
                        <div className="text-xs" style={{ color: "var(--text-faint)" }}>
                          Total Stake
                        </div>
                        <div className="mono font-semibold text-sm">
                          {money(pos.total_stake, pos.currency)}
                        </div>
                      </div>
                      <div>
                        <div className="text-xs" style={{ color: "var(--text-faint)" }}>
                          {pos.settled ? "Realised P&L" : "Expected Profit"}
                        </div>
                        <div
                          className={`mono font-semibold text-sm ${
                            (pos.settled ? pos.realised_pnl || 0 : pos.worst_case_profit) >= 0
                              ? "num-positive"
                              : "text-danger"
                          }`}
                        >
                          {pos.settled
                            ? money(pos.realised_pnl || 0, pos.currency)
                            : money(pos.worst_case_profit, pos.currency)}
                        </div>
                      </div>

                      {/* Action Buttons for Open Active Trades */}
                      {!pos.settled && (
                        <div className="flex items-center gap-2 ml-2">
                          <button
                            className="btn btn-sm"
                            style={{ borderColor: "var(--accent)", color: "var(--accent)" }}
                            onClick={() => setUnwindingItem(pos)}
                            title="Sell all contracts back now at current live market bids"
                          >
                            ⚡ Sell Back Early
                          </button>
                          <button
                            className="btn btn-sm btn-primary"
                            onClick={() => setResolvingItem(pos)}
                            title="Settle this position when the event has finished"
                          >
                            ✓ Hold to Resolution
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Legs breakdown */}
                  <div className="rounded-lg overflow-hidden border" style={{ borderColor: "var(--border)" }}>
                    <div
                      className="grid grid-cols-12 px-3 py-2 text-[11px] font-medium border-b"
                      style={{ background: "var(--bg-sunken)", borderColor: "var(--border)", color: "var(--text-muted)" }}
                    >
                      <div className="col-span-3">Venue / Leg</div>
                      <div className="col-span-3">Outcome</div>
                      <div className="col-span-2 text-right">Price / Odds</div>
                      <div className="col-span-2 text-right">Stake / Contracts</div>
                      <div className="col-span-2 text-right">Status</div>
                    </div>

                    <div className="divide-y" style={{ borderColor: "var(--border)" }}>
                      {pos.legs.map((leg, i) => (
                        <div key={i} className="grid grid-cols-12 px-3 py-2 text-xs items-center">
                          <div className="col-span-3 flex items-center gap-1.5">
                            <span className="chip text-[10px] font-semibold">{leg.side}</span>
                            <span className="font-medium">{leg.venue}</span>
                          </div>
                          <div className="col-span-3 truncate font-medium">{leg.outcome}</div>
                          <div className="col-span-2 text-right mono">
                            {leg.price.toFixed(4)} ({leg.decimal_odds.toFixed(2)}x)
                          </div>
                          <div className="col-span-2 text-right mono font-semibold">
                            {money(leg.stake, pos.currency)} ({num(leg.contracts, 0)}c)
                          </div>
                          <div className="col-span-2 text-right">
                            <span className="text-[11px]" style={{ color: "var(--positive)" }}>
                              ✓ Placed
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </>
      )}

      {/* Hold to Resolution Modal */}
      {resolvingItem && (
        <HoldToResolutionModal
          position={resolvingItem}
          onClose={() => setResolvingItem(null)}
          onSettled={(msg) => {
            setResolvingItem(null);
            showToast(msg);
            load();
          }}
        />
      )}

      {/* Sell Back Early / Unwind Modal */}
      {unwindingItem && (
        <SellBackEarlyModal
          position={unwindingItem}
          onClose={() => setUnwindingItem(null)}
          onSettled={(msg) => {
            setUnwindingItem(null);
            showToast(msg);
            load();
          }}
        />
      )}
    </div>
  );
}

// ------------------------------------------------------------- Modals

function HoldToResolutionModal({
  position,
  onClose,
  onSettled,
}: {
  position: PositionItem;
  onClose: () => void;
  onSettled: (msg: string) => void;
}) {
  const [selectedOutcome, setSelectedOutcome] = useState<string>("");
  const [customPnl, setCustomPnl] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Compute payouts for each outcome
  const outcomes = position.legs.map((l) => l.outcome);

  const calculatePayoutFor = (outcome: string) => {
    if (outcome === "VOID") {
      return { gross: position.total_stake, net: 0.0 };
    }
    if (position.kind === "dutch_no") {
      const gross = position.legs
        .filter((l) => l.outcome.toLowerCase() !== outcome.toLowerCase())
        .reduce((sum, l) => sum + (l.contracts || 0), 0);
      return { gross: round2(gross), net: round2(gross - position.total_stake) };
    }
    const winLeg = position.legs.find(
      (l) => l.outcome.toLowerCase() === outcome.toLowerCase()
    );
    const gross = winLeg ? (winLeg.contracts || 0) : position.total_stake + (position.worst_case_profit || 0);
    return { gross: round2(gross), net: round2(gross - position.total_stake) };
  };

  const handleSelectOutcome = (outcome: string) => {
    setSelectedOutcome(outcome);
    const { net } = calculatePayoutFor(outcome);
    setCustomPnl(net.toString());
  };

  const handleResolve = async () => {
    if (!selectedOutcome && !customPnl) {
      setError("Please select the winning outcome or enter realized P&L.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.resolvePosition(position.id, {
        winning_outcome: selectedOutcome || undefined,
        custom_pnl: customPnl ? parseFloat(customPnl) : undefined,
      });
      onSettled(res.message);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to settle position.",
      );
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="absolute inset-0"
        style={{ background: "rgba(0,0,0,0.65)", backdropFilter: "blur(2px)" }}
        onClick={() => !busy && onClose()}
      />
      <div
        className="relative w-full max-w-lg rounded-xl p-6 flex flex-col gap-4 shadow-2xl"
        style={{ background: "var(--bg)", border: "1px solid var(--border)" }}
      >
        <div className="flex items-start justify-between">
          <div>
            <span className="chip chip-positive text-xs">Hold to Resolution</span>
            <h3 className="text-base font-semibold mt-1">Settle: {position.title}</h3>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              The event has concluded. Select which outcome won to calculate exact payout.
            </p>
          </div>
          <button className="btn btn-sm" onClick={onClose} disabled={busy}>
            ✕
          </button>
        </div>

        <div className="flex flex-col gap-2">
          <div className="label">Select Official Resolution Result</div>
          {outcomes.map((oc) => {
            const { gross, net } = calculatePayoutFor(oc);
            const isSelected = selectedOutcome === oc;
            return (
              <button
                key={oc}
                type="button"
                className={`p-3 rounded-lg border text-left flex items-center justify-between transition-all ${
                  isSelected ? "border-accent bg-accent-soft" : "card card-hover"
                }`}
                onClick={() => handleSelectOutcome(oc)}
              >
                <div>
                  <div className="text-sm font-medium text-white">{oc} Won</div>
                  <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                    Gross Return: {money(gross, position.currency)}
                  </div>
                </div>
                <div className="mono font-semibold text-sm num-positive">
                  {signedMoney(net, position.currency)}
                </div>
              </button>
            );
          })}

          <button
            type="button"
            className={`p-2.5 rounded-lg border text-left flex items-center justify-between text-xs transition-all ${
              selectedOutcome === "VOID" ? "border-accent bg-accent-soft" : "card card-hover"
            }`}
            onClick={() => handleSelectOutcome("VOID")}
          >
            <span style={{ color: "var(--text-muted)" }}>Event Voided / Refunded</span>
            <span className="mono font-medium">Refund Total Stake ($0.00 P&amp;L)</span>
          </button>
        </div>

        <div>
          <label htmlFor="res-pnl" className="label block mb-1">
            Realised P&amp;L Override ({position.currency})
          </label>
          <input
            id="res-pnl"
            type="number"
            step="0.01"
            className="input w-full mono font-semibold text-sm"
            value={customPnl}
            onChange={(e) => setCustomPnl(e.target.value)}
            placeholder="0.00"
            disabled={busy}
          />
        </div>

        {error && (
          <div className="p-2 rounded text-xs" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 pt-2 border-t" style={{ borderColor: "var(--border)" }}>
          <button className="btn btn-sm" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            className="btn btn-sm btn-primary"
            onClick={handleResolve}
            disabled={busy || (!selectedOutcome && !customPnl)}
          >
            {busy ? "Settling…" : "Confirm Resolution"}
          </button>
        </div>
      </div>
    </div>
  );
}

function SellBackEarlyModal({
  position,
  onClose,
  onSettled,
}: {
  position: PositionItem;
  onClose: () => void;
  onSettled: (msg: string) => void;
}) {
  const [quote, setQuote] = useState<UnwindQuoteResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoading(true);
      try {
        const q = await api.unwindQuote(position.id);
        if (mounted) setQuote(q);
      } catch (err) {
        if (mounted) {
          setError(
            err instanceof Error
              ? err.message
              : "Failed to fetch live unwind quote.",
          );
        }
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [position.id]);

  const handleSellBack = async () => {
    if (!confirmed) {
      setError("Please confirm the unwind authorization checkbox.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.sellBackPosition(position.id, {
        confirmed: true,
        note: note.trim() || undefined,
      });
      onSettled(res.message);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to execute sell back orders.",
      );
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="absolute inset-0"
        style={{ background: "rgba(0,0,0,0.65)", backdropFilter: "blur(2px)" }}
        onClick={() => !busy && onClose()}
      />
      <div
        className="relative w-full max-w-xl rounded-xl p-6 flex flex-col gap-4 shadow-2xl"
        style={{ background: "var(--bg)", border: "1px solid var(--border)" }}
      >
        <div className="flex items-start justify-between">
          <div>
            <span className="chip text-xs" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
              ⚡ Sell Back Early (Unwind via API)
            </span>
            <h3 className="text-base font-semibold mt-1">Unwind Position: {position.title}</h3>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              Close out both legs right now across venues at current live order book bids.
            </p>
          </div>
          <button className="btn btn-sm" onClick={onClose} disabled={busy}>
            ✕
          </button>
        </div>

        {loading && <Skeleton rows={4} />}
        {error && <ErrorState message={error} />}

        {quote && !loading && (
          <>
            {/* Live Pricing Summary */}
            <div className="grid grid-cols-3 gap-2.5">
              <div className="card p-3 text-center">
                <div className="label">Initial Stake</div>
                <div className="mono text-sm font-semibold mt-0.5">
                  {money(quote.total_stake, quote.currency)}
                </div>
              </div>
              <div className="card p-3 text-center">
                <div className="label">Estimated Net Proceeds</div>
                <div className="mono text-sm font-semibold mt-0.5">
                  {money(quote.total_proceeds, quote.currency)}
                </div>
              </div>
              <div className="card p-3 text-center">
                <div className="label">Unwind P&amp;L</div>
                <div
                  className={`mono text-sm font-semibold mt-0.5 ${
                    quote.unwind_pnl >= 0 ? "num-positive" : "text-danger"
                  }`}
                >
                  {signedMoney(quote.unwind_pnl, quote.currency)} ({pct(quote.roi_pct / 100)})
                </div>
              </div>
            </div>

            {/* Leg Sell Breakdown */}
            <div className="rounded-lg overflow-hidden border text-xs" style={{ borderColor: "var(--border)" }}>
              <div
                className="grid grid-cols-12 px-3 py-2 font-medium border-b"
                style={{ background: "var(--bg-sunken)", borderColor: "var(--border)", color: "var(--text-muted)" }}
              >
                <div className="col-span-4">Leg / Venue</div>
                <div className="col-span-3 text-right">Entry → Exit Bid</div>
                <div className="col-span-3 text-right">Est. Proceeds</div>
                <div className="col-span-2 text-right">Leg P&amp;L</div>
              </div>

              <div className="divide-y" style={{ borderColor: "var(--border)" }}>
                {quote.legs.map((l, i) => (
                  <div key={i} className="grid grid-cols-12 px-3 py-2 items-center">
                    <div className="col-span-4 truncate font-medium">
                      <span className="chip text-[10px] mr-1">{l.venue}</span>
                      {l.outcome}
                    </div>
                    <div className="col-span-3 text-right mono" style={{ color: "var(--text-muted)" }}>
                      {l.entry_price.toFixed(3)} → <span className="font-semibold text-white">{l.current_bid.toFixed(3)}</span>
                    </div>
                    <div className="col-span-3 text-right mono font-semibold">
                      {money(l.net_proceeds, quote.currency)}
                    </div>
                    <div
                      className={`col-span-2 text-right mono font-semibold ${
                        l.pnl >= 0 ? "num-positive" : "text-danger"
                      }`}
                    >
                      {signedMoney(l.pnl, quote.currency)}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Optional Note */}
            <div>
              <label htmlFor="unwind-note" className="label block mb-1">
                Reference / Strategy Note (Optional)
              </label>
              <input
                id="unwind-note"
                type="text"
                placeholder="e.g. Mean-reversion target reached, closed spread early"
                className="input w-full text-xs"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                disabled={busy}
              />
            </div>

            {/* Enforced Confirmation Box */}
            <div
              className="p-3 rounded-lg border flex items-start gap-2.5 cursor-pointer select-none text-xs"
              style={{
                background: confirmed ? "var(--accent-soft)" : "var(--bg-sunken)",
                borderColor: confirmed ? "var(--accent)" : "var(--border)",
              }}
              onClick={() => !busy && setConfirmed(!confirmed)}
            >
              <input
                type="checkbox"
                id="unwind-confirm"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                disabled={busy}
                className="mt-0.5"
              />
              <label htmlFor="unwind-confirm" className="leading-relaxed cursor-pointer">
                <span className="font-semibold text-white block">
                  I authorize executing sell-back market orders across venues.
                </span>
                <span style={{ color: "var(--text-muted)" }}>
                  This will liquidate all open contracts at best available bids, record the P&amp;L in your ledger, and free your bankroll.
                </span>
              </label>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t" style={{ borderColor: "var(--border)" }}>
              <button className="btn btn-sm" onClick={onClose} disabled={busy}>
                Cancel
              </button>
              <button
                className="btn btn-sm btn-primary"
                onClick={handleSellBack}
                disabled={busy || !confirmed}
                style={{ opacity: confirmed && !busy ? 1 : 0.5 }}
              >
                {busy ? "Selling Back…" : "Confirm Sell Back via API ⚡"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function round2(v: number): number {
  return Math.round(v * 100) / 100;
}
