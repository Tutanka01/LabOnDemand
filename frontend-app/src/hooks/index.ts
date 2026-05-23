import { useEffect, useRef, useState } from "react";

export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);

  return debounced;
}

export function useInterval(callback: () => void, delayMs: number | null) {
  const saved = useRef(callback);

  useEffect(() => {
    saved.current = callback;
  });

  useEffect(() => {
    if (delayMs === null) return;
    const id = setInterval(() => saved.current(), delayMs);
    return () => clearInterval(id);
  }, [delayMs]);
}

export function useLocalStorage<T>(key: string, initial: T): [T, (val: T | ((prev: T) => T)) => void] {
  const [stored, setStored] = useState<T>(() => {
    try {
      const item = localStorage.getItem(key);
      return item ? (JSON.parse(item) as T) : initial;
    } catch {
      return initial;
    }
  });

  const set = (val: T | ((prev: T) => T)) => {
    setStored((prev) => {
      const next = val instanceof Function ? val(prev) : val;
      localStorage.setItem(key, JSON.stringify(next));
      return next;
    });
  };

  return [stored, set];
}
