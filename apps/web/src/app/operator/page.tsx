import { Desk } from "@/components/desk";

export const metadata = { robots: { index: false, follow: false } };

// Financial controls retain server-side operator authorization.
export default function OperatorWorkspace() {
  return <Desk internal />;
}
