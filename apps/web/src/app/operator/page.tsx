import { Desk } from "@/components/desk";
import { notFound } from "next/navigation";

export const metadata = { robots: { index: false, follow: false } };

// Financial controls retain server-side operator authorization.
export default function OperatorWorkspace() {
  if (process.env.VERCEL === "1") notFound();
  return <Desk internal />;
}
