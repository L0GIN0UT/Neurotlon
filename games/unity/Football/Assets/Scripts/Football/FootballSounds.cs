using System.Collections;
using System.Globalization;
using UnityEngine;

namespace Neurotlon.Games.Football
{
    // Обо что ударился мяч: от этого зависит звук. Один материал — один звук, всегда одинаковый:
    // ткань чехла, сетка, мишень (звон металла), штанга и перекладина (металл), земля (отскоки), мяч о мяч (как мяч о землю). У отскоков от земли меняется только громкость.
    public enum FootballSurface { Tarp, Net, Ground, Post, Target, Ball }

    // Звуки игры. Клипы — настоящие записи (ArtSource/Audio/prepare_sounds.py), внешних файлов нет.
    public sealed class FootballSounds : MonoBehaviour
    {
        const float QuietestBounce = 0.25f;               // самый слабый отскок от земли всё равно слышен
        const float FullBounceSpeed = 4f;                 // скорость падения, при которой отскок звучит на полную, м/с
        const float VerdictDelay = 1.0f;                  // итог элемента звучит позже последнего удара, чтобы не перебивать его

        // При записи видео (--record) каждый звук пишется в журнал с игровым временем: по нему собирается звуковая дорожка.
        static readonly bool LogSounds = System.Array.IndexOf(System.Environment.GetCommandLineArgs(), "--record") >= 0;

        [SerializeField] AudioSource source;
        [SerializeField] AudioClip kick;
        [SerializeField] AudioClip touch;
        [SerializeField] AudioClip good;
        [SerializeField] AudioClip soft;
        [SerializeField] AudioClip miss;
        [SerializeField] AudioClip tick;
        [SerializeField] AudioClip end;
        [SerializeField] AudioClip tarp;
        [SerializeField] AudioClip net;
        [SerializeField] AudioClip ground;
        [SerializeField] AudioClip target;
        [SerializeField] AudioClip post;

        public void Play(FootballEvent e)
        {
            switch (e.Kind)
            {
                case FootballEventKind.ElementStarted: Play(tick); break;
                case FootballEventKind.Touch: Play(touch); break;
                case FootballEventKind.Kick: Play(kick); break;
                case FootballEventKind.Landed:
                    // у передачи и удара звук приземления зависит от материала (Impact); итог — по окончании элемента
                    if (e.Element == FootballElement.Stop) Play(Verdict(e.Points));
                    break;
                case FootballEventKind.ElementFinished:
                    if (e.Element == FootballElement.Pass || e.Element == FootballElement.Kick) StartCoroutine(PlayLater(Verdict(e.Points), VerdictDelay));
                    break;
                case FootballEventKind.GameOver: StartCoroutine(PlayLater(end, VerdictDelay + 0.6f)); break;      // после итога элемента, не поверх удара
            }
        }

        // Удар мяча о поверхность. speed — скорость мяча, м/с: от неё зависит громкость только отскока от земли;
        // остальные материалы звучат всегда одинаково, откуда и куда бы ни попал мяч.
        public void Impact(FootballSurface surface, float speed)
        {
            switch (surface)
            {
                case FootballSurface.Tarp: Play(tarp); break;
                case FootballSurface.Net: Play(net); break;
                case FootballSurface.Post: Play(post); break;
                case FootballSurface.Target: Play(target); break;
                default: Play(ground, Mathf.Lerp(QuietestBounce, 1f, Mathf.Clamp01(speed / FullBounceSpeed))); break;     // земля и мяч о мяч: глухой удар
            }
        }

        public void Metronome()
        {
            Play(tick);
        }

        AudioClip Verdict(int points)
        {
            return points >= 2 ? good : (points == 1 ? soft : miss);
        }

        IEnumerator PlayLater(AudioClip clip, float seconds)
        {
            yield return new WaitForSeconds(seconds);
            Play(clip);
        }

        void Play(AudioClip clip, float volume = 1f)
        {
            if (clip == null || source == null) return;
            source.PlayOneShot(clip, volume);
            if (LogSounds)
                Debug.Log("NTSOUND " + Time.time.ToString("F3", CultureInfo.InvariantCulture) + " " + clip.name + " " + (volume * source.volume).ToString("F3", CultureInfo.InvariantCulture));
        }
    }
}
