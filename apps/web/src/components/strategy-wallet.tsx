"use client";

import { useEffect, useRef, useState } from "react";
import { Wallet as WalletIcon, LoaderCircle } from "lucide-react";
import { discoverWallets, WalletSession, type Wallet, type WalletState } from "@/lib/wallet";
import type { Episode } from "@/lib/types";
import { WalletAuth } from "./wallet-auth";

export function StrategyWallet({ episodes }: { episodes: Episode[] }) {
  const session = useRef<WalletSession | null>(null);
  const [wallet, setWallet] = useState<WalletState>({ status: "idle", address: null, chainId: null, error: null, revision: 0 });
  const [wallets, setWallets] = useState<Wallet[]>([]), [selected, setSelected] = useState("");
  const [now, setNow] = useState(0);
  useEffect(() => {
    const current = new WalletSession(); session.current = current;
    const unsubscribe = current.subscribe(setWallet), stopDiscovery = discoverWallets(window, setWallets);
    setNow(Date.now()); const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => { unsubscribe(); current.disconnect(); stopDiscovery(); clearInterval(timer); };
  }, []);
  return <section className="testnet-panel user-account" aria-labelledby="strategy-wallet-title">
    <div className="panel-heading"><h2 id="strategy-wallet-title"><WalletIcon size={17} /> My strategies</h2></div>
    <div className="testnet-body">
      <p>Connect your wallet, sign in, then send a BTC setup for review. No deposit is needed to pitch.</p>
      {wallet.status === "connected" ? <>
        <dl className="testnet-addresses"><div><dt>Connected wallet</dt><dd>{wallet.address}</dd></div></dl>
        <button className="button button--secondary" onClick={() => session.current?.disconnect()}>Disconnect</button>
      </> : wallets.length ? <div className="user-account-controls">
        {wallets.length > 1 && <label>Wallet<select value={selected || wallets[0].id} disabled={wallet.status === "connecting"} onChange={event => setSelected(event.target.value)}>
          {wallets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
        <button className="button button--primary" disabled={wallet.status === "connecting"} onClick={() => {
          const provider = wallets.find(item => item.id === (selected || wallets[0].id))?.provider;
          if (provider) void session.current?.connect(provider);
        }}>{wallet.status === "connecting" ? <LoaderCircle size={16} className="spinner" /> : <WalletIcon size={16} />}{wallet.status === "connecting" ? "Waiting for wallet…" : "Connect wallet"}</button>
      </div> : <p className="notice">Open this site in a browser with an Ethereum wallet such as MetaMask or Rabby installed. No wallet was detected here.</p>}
      {wallet.status === "connecting" && <button className="text-button" onClick={() => session.current?.disconnect()}>Cancel connection</button>}
      {wallet.error && <p className="form-error" role="alert">{wallet.error}</p>}
      {wallet.address && wallet.chainId && session.current && <WalletAuth strategyOnly network="mainnet" key={`${wallet.address}:${wallet.revision}`}
        address={wallet.address} chainId={wallet.chainId} session={session.current} now={now} episodes={episodes} />}
    </div>
  </section>;
}
