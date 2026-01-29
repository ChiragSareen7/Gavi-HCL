import React from "react";

export const metadata = {
  title: "Scam Compare",
  description: "Compare base vs fine-tuned scam classifier outputs",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0 }}>{children}</body>
    </html>
  );
}


