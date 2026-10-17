/** Explicit wallet connection and tightly scoped authentication. No exchange signing. */
import { messageHex, validateAuthChallenge } from "./wallet-auth.ts";
import { validateFinancialJob, type FinancialKind, type BoundPlan } from "./user-financial.ts";
import type { ExecutionProfile } from "./user-consent.ts";

export type Provider = {
  request(args: { method: string; params?: unknown[] }): Promise<unknown>;
  on(event: string, listener: (value: unknown) => void): void;
  removeListener(event: string, listener: (value: unknown) => void): void;
};
export type Wallet = { id: string; name: string; provider: Provider };
export type WalletState = {
  status: "idle" | "connecting" | "connected" | "error";
  address: string | null; chainId: string | null; error: string | null; revision: number;
};
export function normalizeAddress(value: unknown): string | null {
  return typeof value === "string" && /^0x[0-9a-fA-F]{40}$/.test(value) && !/^0x0{40}$/.test(value) ? value.toLowerCase() : null;
}
function account(value: unknown): string | null {
  return Array.isArray(value) && value.length ? normalizeAddress(value[0]) : null;
}
function chain(value: unknown): string | null {
  return typeof value === "string" && /^0x[0-9a-fA-F]{1,16}$/.test(value) ? value.toLowerCase() : null;
}
function isProvider(value: unknown): value is Provider {
  return !!value && typeof value === "object" && ["request", "on", "removeListener"].every(key => typeof (value as Record<string, unknown>)[key] === "function");
}

export function discoverWallets(target: Window, update: (wallets: Wallet[]) => void): () => void {
  const wallets: Wallet[] = [];
  const announce = (event: Event) => {
    const detail = (event as CustomEvent).detail;
    if (!detail || !isProvider(detail.provider) || typeof detail.info?.uuid !== "string" ||
        !/^[\w-]{1,80}$/.test(detail.info.uuid) || typeof detail.info?.name !== "string" || !detail.info.name.trim()) return;
    if (wallets.some(wallet => wallet.provider === detail.provider || wallet.id === detail.info.uuid)) return;
    // Metadata is untrusted. Never render wallet-supplied SVGs or image URLs.
    wallets.push({ id: detail.info.uuid, name: detail.info.name.trim().slice(0, 64), provider: detail.provider });
    update([...wallets]);
  };
  target.addEventListener("eip6963:announceProvider", announce);
  target.dispatchEvent(new Event("eip6963:requestProvider"));
  const fallback = (target as Window & { ethereum?: unknown }).ethereum;
  if (isProvider(fallback) && !wallets.some(wallet => wallet.provider === fallback)) {
    wallets.push({ id: "injected", name: "Browser wallet", provider: fallback });
  }
  update([...wallets]);
  return () => target.removeEventListener("eip6963:announceProvider", announce);
}

export class WalletSession {
  private state: WalletState = { status: "idle", address: null, chainId: null, error: null, revision: 0 };
  private generation = 0;
  private release: (() => void) | null = null;
  private provider: Provider | null = null;
  private listeners = new Set<(state: WalletState) => void>();
  snapshot(): WalletState { return { ...this.state }; }
  subscribe(listener: (state: WalletState) => void): () => void {
    this.listeners.add(listener); listener(this.snapshot());
    return () => { this.listeners.delete(listener); };
  }
  private update(next: Omit<WalletState, "revision">) {
    this.state = { ...next, revision: this.state.revision + 1 };
    this.listeners.forEach(listener => listener(this.snapshot()));
  }
  disconnect() {
    this.generation++; this.release?.(); this.release = null;
    this.provider = null;
    this.update({ status: "idle", address: null, chainId: null, error: null });
  }
  async connect(provider: Provider) {
    this.disconnect();
    const generation = this.generation;
    this.update({ status: "connecting", address: null, chainId: null, error: null });
    const changed = () => {
      // Reconnect explicitly after a wallet event; invalidate pending requests immediately.
      this.disconnect();
      this.update({ status: "idle", address: null, chainId: null, error: "Wallet account or network changed. Connect again to refresh the view." });
    };
    this.release = () => {
      for (const event of ["accountsChanged", "chainChanged", "disconnect"]) {
        try { provider.removeListener(event, changed); } catch { /* A failing provider cannot retain local session authority. */ }
      }
    };
    try {
      provider.on("accountsChanged", changed); provider.on("chainChanged", changed); provider.on("disconnect", changed);
      const accounts = await provider.request({ method: "eth_requestAccounts" });
      if (generation !== this.generation) return;
      const address = account(accounts);
      if (!address) throw new Error("No valid account.");
      const chainId = chain(await provider.request({ method: "eth_chainId" }));
      if (generation !== this.generation) return;
      if (!chainId) throw new Error("Invalid chain.");
      this.provider = provider;
      this.update({ status: "connected", address, chainId, error: null });
    } catch (error) {
      if (generation !== this.generation) return;
      this.disconnect();
      const code = typeof error === "object" && error ? (error as { code?: number }).code : null;
      this.update({ status: "error", address: null, chainId: null, error: code === 4001 ? "Connection declined. No signature or transaction was requested." :
        code === -32002 ? "A wallet request is already pending. Open your wallet to resolve it." : "The wallet could not connect. Unlock it and retry, or watch a public address." });
    }
  }

  async signMainnetAuthentication(value: unknown, origin: string): Promise<string> {
    return this.authenticate(value, origin, "mainnet");
  }
  async signAuthentication(value: unknown, origin: string): Promise<string> {
    return this.authenticate(value, origin, "testnet");
  }
  private async authenticate(value: unknown, origin: string, network: "testnet" | "mainnet"): Promise<string> {
    const provider = this.provider, generation = this.generation, state = this.snapshot();
    if (!provider || state.status !== "connected" || !state.address || !state.chainId) throw new Error("Connect the wallet before signing in.");
    const challenge = validateAuthChallenge(value, state.address, origin, state.chainId, Date.now(), network);
    const current = () => {
      if (generation !== this.generation || provider !== this.provider || state.revision !== this.state.revision) throw new Error("Wallet changed. Reconnect and prepare a fresh sign-in message.");
      validateAuthChallenge(challenge, state.address!, origin, state.chainId!, Date.now(), network);
    };
    const checkProvider = async () => {
      const accounts = await provider.request({ method: "eth_accounts" }); current();
      const chainId = await provider.request({ method: "eth_chainId" }); current();
      if (account(accounts) !== state.address || chain(chainId) !== state.chainId) {
        this.disconnect(); throw new Error("Wallet account or network changed. Reconnect before signing in.");
      }
    };
    await checkProvider(); current();
    const signature = await provider.request({ method: "personal_sign", params: [messageHex(challenge.message), state.address] });
    current();
    if (typeof signature !== "string" || !/^0x[0-9a-fA-F]{130}$/.test(signature)) throw new Error("The wallet returned an invalid authentication signature.");
    await checkProvider(); current();
    return signature;
  }

  async signMainnetFinancial(value: unknown, profile: ExecutionProfile, kind: FinancialKind, origin: string, plan?: BoundPlan): Promise<string> {
    return this.financial(value, profile, kind, origin, plan, "mainnet");
  }
  async signFinancial(value: unknown, profile: ExecutionProfile, kind: FinancialKind, origin: string, plan?: BoundPlan): Promise<string> {
    return this.financial(value, profile, kind, origin, plan, "testnet");
  }
  private async financial(value: unknown, profile: ExecutionProfile, kind: FinancialKind, origin: string, plan: BoundPlan | undefined, network: "testnet" | "mainnet"): Promise<string> {
    const provider = this.provider, generation = this.generation, state = this.snapshot();
    if (!provider || state.status !== "connected" || state.address !== profile.address || !state.chainId) throw new Error("Connect the exact wallet before financial signing.");
    const job = structuredClone(validateFinancialJob(value, profile, kind, origin, state.chainId, plan, Date.now(), network));
    const current = () => {
      if (generation !== this.generation || provider !== this.provider || state.revision !== this.state.revision) throw new Error("Wallet changed during financial signing.");
      validateFinancialJob(job, profile, kind, origin, state.chainId!, plan, Date.now(), network);
    };
    const checkProvider = async () => {
      const accounts = await provider.request({ method: "eth_accounts" }); current();
      const network = await provider.request({ method: "eth_chainId" }); current();
      if (account(accounts) !== state.address || chain(network) !== state.chainId) { this.disconnect(); throw new Error("Wallet changed before financial proof submission."); }
    };
    await checkProvider(); current();
    const signature = await provider.request({ method: "eth_signTypedData_v4", params: [state.address, JSON.stringify(job.typed_data)] });
    current();
    if (typeof signature !== "string" || !/^0x[0-9a-fA-F]{130}$/.test(signature)) throw new Error("Invalid financial wallet signature.");
    await checkProvider(); current();
    return signature;
  }
}
