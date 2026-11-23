import { motion, useReducedMotion } from 'motion/react'
import type { ReactNode } from 'react'

/** Направление перехода: 1 — вперёд по шагам, -1 — назад. */
export type Direction = 1 | -1

const SHIFT = 64

/** Обёртка экрана: новый въезжает и проявляется из размытия, старый уходит в противоположную сторону. */
export function Screen({ direction, children }: { direction: Direction; children: ReactNode }) {
  const reduce = useReducedMotion()
  return (
    <motion.section
      className="screen"
      custom={direction}
      variants={{
        enter: (d: Direction) => ({
          opacity: 0,
          x: reduce ? 0 : d * SHIFT,
          scale: 0.985,
          filter: 'blur(10px)',
        }),
        center: {
          opacity: 1,
          x: 0,
          scale: 1,
          filter: 'blur(0px)',
          transition: reduce
            ? { duration: 0.15 }
            : { type: 'spring', visualDuration: 0.5, bounce: 0.12, filter: { duration: 0.3 } },
        },
        exit: (d: Direction) => ({
          opacity: 0,
          x: reduce ? 0 : -d * SHIFT,
          scale: 0.985,
          filter: 'blur(10px)',
          transition: { duration: reduce ? 0.1 : 0.22, ease: 'easeIn' },
        }),
      }}
      initial="enter"
      animate="center"
      exit="exit"
    >
      {children}
    </motion.section>
  )
}
