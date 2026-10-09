import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Daybreak · Daily AI News Agent",
  description: "An autonomous, source-verifiable daily AI briefing."
};
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
