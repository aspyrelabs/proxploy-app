import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function pveWebUrl(address: string): string {
  try {
    const u = new URL(address)
    if (!u.port) u.port = '8006'
    return u.toString().replace(/\/$/, '')
  } catch {
    return address
  }
}
