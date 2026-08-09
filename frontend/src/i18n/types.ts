import type { en } from './en'

export type Messages = typeof en
export type Namespace = keyof Messages & string

/**
 * Every valid key, as `namespace.leaf`. Exactly one dot: catalogs are two
 * levels deep on purpose, so this resolves as a cheap distributive mapped type
 * rather than a recursive walk over every leaf in the tree. `npm run check`
 * gates on `tsc --noEmit`, and recursion at catalog scale is what makes that
 * slow.
 */
export type MessageKey = {
  [N in Namespace]: `${N}.${keyof Messages[N] & string}`
}[Namespace]

type Ns<K extends MessageKey> = K extends `${infer N}.${string}` ? N & Namespace : never
type Leaf<K extends MessageKey> = K extends `${string}.${infer L}` ? L : never

/** The literal English string behind a key. Drives placeholder typing below. */
export type Value<K extends MessageKey> = Messages[Ns<K>][Leaf<K> & keyof Messages[Ns<K>]] & string

/** `'{a} and {b}'` -> `'a' | 'b'` */
type Placeholders<S extends string> = S extends `${string}{${infer P}}${infer Rest}`
  ? P | Placeholders<Rest>
  : never

export type Vars = Record<string, string | number>

/**
 * Interpolation vars are required iff the English value has placeholders, and
 * the accepted names are read straight off that value — so a renamed or
 * forgotten placeholder is a compile error, not a `{message}` rendered raw.
 */
export type Args<K extends MessageKey> = [Placeholders<Value<K>>] extends [never]
  ? []
  : [vars: Record<Placeholders<Value<K>>, string | number>]

/** Bases of plural key pairs — `'ns.thing'` for a `ns.thing_other` key. */
export type PluralBase = MessageKey extends infer K
  ? K extends `${infer B}_other`
    ? B
    : never
  : never

/**
 * A translated catalog. Every namespace and every key is optional: a partial
 * translation compiles, and each missing key falls back to English on its own.
 *
 * Values widen to `string` — `en` is declared `as const` so its values carry
 * literal types (which is what makes placeholder checking work), and a
 * translation obviously must not be required to repeat the English literal.
 */
export type PartialMessages = {
  [N in Namespace]?: { [K in keyof Messages[N]]?: string }
}
