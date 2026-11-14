"use client";
import { initializePaddle, type Paddle } from "@paddle/paddle-js";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export function Checkout({ userId, email }: { userId: string; email: string | null }) {
  const router = useRouter();
  const [paddle, setPaddle] = useState<Paddle | undefined>();
  const token = process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN ?? "";
  const priceId = process.env.NEXT_PUBLIC_PADDLE_PRICE_ID ?? "";
  const environment = process.env.NEXT_PUBLIC_PADDLE_ENV === "production" ? "production" : "sandbox";

  useEffect(() => {
    if (!token) return;
    initializePaddle({
      environment,
      token,
      eventCallback: (event) => {
        // The webhook is the source of truth; refresh so the server re-reads entitlements.
        if (event.name === "checkout.completed") setTimeout(() => router.refresh(), 2500);
      },
    }).then(setPaddle);
  }, [token, environment, router]);

  if (!token || !priceId) {
    return <p className="warn">결제가 아직 설정되지 않았습니다 (NEXT_PUBLIC_PADDLE_CLIENT_TOKEN, NEXT_PUBLIC_PADDLE_PRICE_ID).</p>;
  }
  return (
    <button
      type="button"
      disabled={!paddle}
      onClick={() =>
        paddle?.Checkout.open({
          items: [{ priceId, quantity: 1 }],
          // Links the Paddle subscription to this user (sion_api.billing reads sion_user_id).
          customData: { sion_user_id: userId },
          ...(email ? { customer: { email } } : {}),
        })
      }
    >
      {paddle ? "결제하기" : "결제 모듈 불러오는 중…"}
    </button>
  );
}
