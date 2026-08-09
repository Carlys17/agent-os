/**
 * The catalog registry: where every namespace lands and where `t()` reads.
 *
 * `t()` is synchronous, so the English fallback it consults must already be in
 * memory — but assembling that fallback in one eager module drags every view's
 * copy into the entry bundle, which is what made initial JS grow with each
 * migrated view (#261). So the fallback is assembled *by import*: a namespace
 * module registers itself when it is evaluated, and the bundler places it in
 * whichever chunk imports it. The shell's namespaces are imported by
 * `i18n/index.ts` and stay eager; a view's namespace is imported by that view
 * and travels inside its lazy chunk.
 *
 * Registration is a module-scope side effect, so a namespace is present before
 * the importing module's body runs — which is what keeps module-scope `t()`
 * calls (view `logic.ts` label maps, imperative DOM builders) working.
 *
 * Deliberately import-free. Catalog modules import this one, so anything it
 * imported back would form a cycle whose `const` initialisers are still in the
 * temporal dead zone when the first `defineNamespace()` call fires.
 */

type Leaves = Record<string, string | undefined>

/** A locale's messages, loosely typed — `PartialMessages` is the public shape. */
export type LooseCatalog = Record<string, Leaves | undefined>

/**
 * Live: namespaces appear as their modules evaluate, and every holder of this
 * object (the `en` entry below, `t()`'s fallback) observes them immediately.
 */
const EN: LooseCatalog = {}

const CATALOGS = new Map<string, LooseCatalog>([['en', EN]])

/** The English fallback, for `t()`'s second lookup rung. */
export const enFallback: LooseCatalog = EN

/**
 * Declare an English namespace and register it. Returns the messages unchanged
 * so the module can still `export const <ns> = defineNamespace(...)`, which is
 * what `MessageKey` is derived from.
 */
export function defineNamespace<M extends Readonly<Record<string, string>>>(
  namespace: string,
  messages: M,
): M {
  EN[namespace] = messages
  return messages
}

/** Registered namespace names, in registration order. For tests. */
export function registeredNamespaces(): string[] {
  return Object.keys(EN)
}

export function putCatalog(tag: string, messages: LooseCatalog): void {
  CATALOGS.set(tag, messages)
}

export function hasCatalog(tag: string): boolean {
  return CATALOGS.has(tag)
}

export function catalogFor(locale: string): LooseCatalog {
  return CATALOGS.get(locale) ?? EN
}
