"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { equityDelta, tankAgents, tankPhase } from "@/lib/tank-scene";
import type { LaunchFigures } from "@/lib/launch-preview";
import { money, statusLabel, type Episode, type State } from "@/lib/types";
import styles from "./agent-tank.module.css";

const phaseText = { offline: "Waiting for connection", idle: "Standing by", reviewing: "Review in progress", approved: "Entry pending", submitting: "Submitting order", open: "Position open", closing: "Closing position", closed: "Trade closed", vetoed: "Setup declined", attention: "Execution needs attention" };
const stationX = [172, 440, 708];
const routine = [
  { actor: 0, action: "Reading the market", positions: [[172, 206], [510, 298], [708, 206]], speech: ["Watching the tape", "Entry. Stop. Size.", "Capital check"], work: [true, false, true] },
  { actor: 0, action: "Passing the thesis", positions: [[335, 290], [440, 206], [610, 310]], speech: ["Over to risk", "Checking limits", "Watching exposure"], work: [false, true, false] },
  { actor: 1, action: "Checking the downside", positions: [[520, 292], [440, 206], [708, 206]], speech: ["Review the thesis", "Protect the downside", "Sizing the entry"], work: [false, true, true] },
  { actor: 1, action: "Reviewing the size", positions: [[172, 206], [610, 286], [708, 206]], speech: ["Back to the tape", "Budget before entry", "Checking the budget"], work: [true, false, true] },
  { actor: 2, action: "Following execution", positions: [[268, 305], [440, 206], [540, 290]], speech: ["Watching BTC", "Keep the stop", "Tracking execution"], work: [false, true, false] },
  { actor: 2, action: "Tracking the position", positions: [[172, 206], [310, 296], [708, 206]], speech: ["Next market scan", "Risk stays capped", "Tracking PnL"], work: [true, false, true] },
] as const;

function PixelAgent({ kind }: { kind: number }) {
  return <g className={styles.sprite} shapeRendering="crispEdges">
    <ellipse cx="0" cy="38" rx="24" ry="5" className={styles.shadow} />
    <g className={styles.leftLeg}><path d="M-13 23h-8v7h-9v5h15V30h7v-7" /></g><g className={styles.rightLeg}><path d="M13 23h8v7h9v5H15V30H8v-7" /></g>
    <path className={styles.shellDark} d="M-18-4h36v29H12v7h-24v-7h-6z" />
    <path className={styles.shell} d="M-13-12h26v7h7v22h-6v7h-28v-7h-6V-5h7z" />
    <path className={styles.shellLight} d="M-10-8h20v5h-20zM-15-3h6v15h-6z" />
    <g className={styles.claws}><path className={styles.shellDark} d="M-19 4h-8V-8h-9v-15h7v9h5v-9h7v15h-4v12M19 4h8V-8h9v-15h-7v9h-5v-9h-7v15h4v12" /><path className={styles.shell} d="M-29-12h9v-7h-3v4h-3v-7h-6v7h3M29-12h-9v-7h3v4h3v-7h6v7h-3" /></g>
    <path className={styles.eyeStalk} d="M-11-12v-8h7v8M4-12v-8h7v8" />
    <path className={styles.eyes} d="M-10-19h6v7h-6zM4-19h6v7H4z" />
    <path className={styles.pupils} d="M-7-17h3v4h-3zM7-17h3v4H7zM-4 8h8v3h-8z" />
    {kind === 1 && <path className={styles.accessory} d="M-15-13h30v3H-15zM-14-10h11v9h-11zM3-10h11v9H3z" fill="none" strokeWidth="3" />}
    {kind === 2 && <path className={styles.accessory} d="M-5 19H5l-2 5 3 9H-6l3-9z" />}
  </g>;
}

function Workstation({ x, index, chart, state, equity }: { x: number; index: number; chart: string; state: State | null; equity: string | null }) {
  return <g transform={`translate(${x} 92)`} className={styles.station}>
    <path className={styles.deskShadow} d="M-98 87H100v20H-98z" />
    <path className={styles.deskLeg} d="M-90 70h10v40h-10zM80 70h10v40H80z" />
    <path className={styles.deskTop} d="M-103 51H103v24H-103z" />
    <path className={styles.deskEdge} d="M-103 75H103v9H-103z" />
    <path className={styles.hardware} d="M-70-7h140v63H-70zM-7 53H7v8H-7zM-20 60h40v4h-40z" />
    <path className={styles.screen} d="M-65-2H65v49H-65z" />
    <path className={styles.screenGrid} d="M-60 12H60M-60 27H60M-60 42H60M-30 3v39M0 3v39M30 3v39" />
    {index === 0 && chart && <polyline points={chart} fill="none" className={styles.chartLine} strokeWidth="2" />}
    <text x="-58" y="8" className={styles.screenLabel}>{index === 0 ? "BTC / USDC" : index === 1 ? "RISK CONTROL" : "EXECUTION"}</text>
    {index === 1 && <><text x="-55" y="25" className={styles.terminalValue}>{state ? `${Number(state.policy.risk_fraction) * 100}% MAX LOSS` : "AWAITING DATA"}</text><text x="-55" y="39" className={styles.screenLabel}>{state ? `UP TO ${state.policy.max_leverage}x LEVERAGE` : "LIMITS REQUIRED"}</text></>}
    {index === 2 && <><text x="-55" y="25" className={styles.terminalValue}>{money(equity)}</text><text x="-55" y="39" className={styles.screenLabel}>ACCOUNT EQUITY / USDC</text></>}
    <path className={styles.keyboard} d="M-45 68h73v4h-73zM44 64h9v8h-9z" />
    <g className={styles.terminalActivity}>{[0, 1, 2, 3].map(n => <rect key={n} x={38 + n * 5} y={35 - n * 4} width="3" height={8 + n * 4} style={{animationDelay: `${n * -180}ms`}} />)}</g>
    <path className={styles.cup} d="M74 43h12v17H74zM86 46h5v9h-5" />
    <rect x="-49" y="91" width="98" height="18" rx="2" className={styles.nameplate} />
    <text x="0" y="103" textAnchor="middle" className={styles.stationName}>{tankAgents[index].name.toUpperCase()}</text>
  </g>;
}

export function AgentTank({ state, episode, internal = false, illustrative = null }: { state: State | null; episode?: Episode; internal?: boolean; illustrative?: LaunchFigures | null }) {
  const [beat, setBeat] = useState(0);
  useEffect(() => { const timer = setInterval(() => setBeat(b => (b + 1) % routine.length), 1800); return () => clearInterval(timer); }, []);
  const moment = routine[beat];
  const selected = moment.actor;
  const [delta, setDelta] = useState<string | null>(null);
  const equity = illustrative?.equity ?? state?.account.equity ?? null;
  const lastEquity = useRef<string | null>(null);
  useEffect(() => {
    setDelta(equityDelta(lastEquity.current, equity));
    lastEquity.current = equity;
    const timeout = setTimeout(() => setDelta(null), 4000);
    return () => clearTimeout(timeout);
  }, [equity]);
  const available = !!state && !state.service.data_stale;
  const phase = tankPhase(episode, available);
  const agent = tankAgents[selected];
  const review = agent.key === "banker" ? undefined : episode?.reviews[agent.key];
  const candles = available ? state?.market?.candles.slice(-28) ?? [] : [];
  const prices = candles.map(c => Number(c.close)).filter(Number.isFinite);
  const low = Math.min(...prices), span = Math.max(...prices) - low;
  const chart = prices.length > 1 ? prices.map((p, i) => `${-58 + i * 116 / (prices.length - 1)},${40 - (span ? (p - low) / span : .5) * 23}`).join(" ") : "";
  const message = !available ? "Waiting for the latest tank observations." : review?.summary || (agent.key === "banker" && episode ? episode.reason : ["Watching BTC. Ready to review the next setup.", "Every entry must pass the coded risk limits.", "Capital and execution follow the approved limits."][selected]);
  const speech = !available ? ["Connecting…", "Waiting for data", "Account sync"] : tankAgents.map((a, i) => {
    const r = a.key === "banker" ? undefined : episode?.reviews[a.key];
    if (r) return r.verdict === "approve" ? "Review approved" : "Review declined";
    if (a.key === "banker" && ["open", "submitting", "attention"].includes(phase)) return phase === "open" ? "Position open" : phase === "submitting" ? "Sending order…" : "Needs attention";
    return moment.speech[i];
  });
  return <div className={styles.tank} data-phase={phase} data-beat={beat}>
    <div className={styles.hud}>
      <div className={styles.roomLabel}><span className={styles.signal} /><span>THE TRADING FLOOR<small>{available ? moment.action : phaseText[phase]}</small></span></div>
      <div className={styles.balance}><span>BOT EQUITY · USDC</span><strong key={equity ?? "unknown"} className={styles.balanceTick}>{money(equity)}</strong>{delta && <span key={equity} className={`${styles.delta} ${delta.startsWith("−") ? styles.loss : ""}`}>{delta}</span>}</div>
    </div>
    <div className={styles.room}>
      <svg viewBox="0 0 880 380" role="img" aria-label={`Three agents on the trading floor. ${phaseText[phase]}.`} className={styles.scene}>
        <defs><pattern id="tank-floor-boards" width="110" height="32" patternUnits="userSpaceOnUse"><rect width="110" height="32" className={styles.floor} /><path d="M0 0H110M0 31H110M55 0v16M0 16h110M110 16v16" className={styles.floorSeam} fill="none" /></pattern></defs>
        <rect width="880" height="380" className={styles.wall} />
        <path d="M0 66h880v314H0z" fill="url(#tank-floor-boards)" />
        <path className={styles.baseboard} d="M0 61h880v8H0z" />
        {[40, 733].map(x => <g key={x} transform={`translate(${x} 12)`}><rect width="107" height="40" className={styles.windowFrame} /><rect x="5" y="5" width="97" height="30" className={styles.window} /><path d="M10 28h10v-8h9v12h12V16h11v16h11V10h13v22h19" className={styles.skyline} /><path d="M53 5v30" className={styles.windowFrame} stroke="currentColor" /></g>)}
        <rect x="310" y="10" width="260" height="39" rx="2" className={styles.signBoard} /><text x="440" y="35" textAnchor="middle" className={styles.roomSign}>LOBSTER DESK</text>
        <text x="440" y="264" textAnchor="middle" className={styles.floorMark}>SMALL POSITIONS. BIG IDEAS.</text>
        {stationX.map((x, i) => <Workstation key={i} x={x} index={i} chart={chart} state={available ? state : null} equity={illustrative ? equity : available ? equity : null} />)}
        <g className={styles.signalRoute} aria-hidden="true"><path d="M172 214v74h268v-74M440 288h268v-74" /><g className={styles.dispatchPacket}><rect x="-9" y="-6" width="18" height="12" rx="2" /><path d="m-8-5 8 6 8-6" /></g></g>
        <g transform="translate(410 297)"><ellipse cx="30" cy="15" rx="103" ry="31" className={styles.rugEdge} /><ellipse cx="30" cy="12" rx="93" ry="26" className={styles.rug} /><ellipse cx="30" cy="12" rx="65" ry="17" className={styles.rugRing} fill="none" /><text x="30" y="16" textAnchor="middle" className={styles.rugText}>THE COLLECTIVE</text></g>
        {[40, 830].map(x => <g key={x} transform={`translate(${x} 303)`}><path className={styles.pot} d="M-11 3h22l-3 22H-8z" /><path className={styles.plant} d="M-3 4v-28h7V4M-3-7h-13v-15h6v8h7M4-15h10v-16h6v23H4" /></g>)}
        {tankAgents.map((a, i) => <g key={a.key} className={`${styles.agent} ${styles[`agent${i}`]} ${selected === i ? styles.selected : ""}`} style={{ "--agent-x": `${moment.positions[i][0]}px`, "--agent-y": `${moment.positions[i][1]}px` } as CSSProperties}>
          <g className={moment.work[i] ? styles.working : styles.roaming}><g className={styles.body}><PixelAgent kind={i} /></g>
            <g className={styles.bubble}><rect x="-75" y="-64" width="150" height="25" rx="4" /><path d="M-5-39h10l-5 6z" /><text x="0" y="-47" textAnchor="middle">{speech[i]}</text></g>
          </g>
        </g>)}
        {delta && <g key={equity} className={`${styles.earningsBurst} ${delta.startsWith("−") ? styles.loss : ""}`} transform="translate(708 235)"><text textAnchor="middle">{delta}</text>{[0,1,2,3,4].map(n => <rect key={n} x={n * 15 - 30} y={n % 2 * 10} width="5" height="5" />)}</g>}
        <g transform="translate(44 353)"><circle r="3" className={styles.signal} /><text x="12" y="4" className={styles.floorCaption}>{available ? "BTC / USDC" : "AWAITING DATA"}</text></g>
        <text x="837" y="357" textAnchor="end" className={styles.floorCaption}>HYPERLIQUID</text>
      </svg>
    </div>
    <div className={styles.roster} aria-label="Agent roles">{tankAgents.map((a, i) => <div key={a.key} data-active={selected === i} className={`${styles.agentButton} ${styles[`agent${i}`]}`}><span className={styles.agentDot} /><span>{a.name}<small>{a.role}</small></span><span className={styles.agentState}>{!available ? "OFFLINE" : (a.key !== "banker" && episode?.reviews[a.key]) ? episode.reviews[a.key]?.verdict === "approve" ? "IN" : "OUT" : "•"}</span></div>)}</div>
    <div className={styles.commentary}><strong>{agent.name}<span> / {agent.role}</span></strong><p>{message}</p></div>
    <div className={styles.verdict}><span>{episode ? `EP ${episode.id.slice(0, 6).toUpperCase()}` : state ? "AWAITING FIRST SETUP" : "AWAITING UPDATES"}</span><strong>{available && episode && phase !== "vetoed" ? statusLabel(episode.status) : phaseText[phase]}</strong>{internal && <span>PAPER</span>}</div>
  </div>;
}
