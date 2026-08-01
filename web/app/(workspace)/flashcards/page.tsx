import type { Metadata } from "next";
import FlashcardsWorkspace from "@/components/flashcards/FlashcardsWorkspace";

export const metadata: Metadata = { title: "Flashcards" };

export default function FlashcardsPage() {
  return <FlashcardsWorkspace />;
}
