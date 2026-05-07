import { useSearchParams } from 'next/navigation';

export default function DownloadPage() {
  const searchParams = useSearchParams();
  const photoUrl = searchParams.get('url');

  return (
    <div className="min-h-screen bg-zinc-950 text-white flex flex-col items-center justify-center p-6 font-sans">
      <div className="max-w-sm w-full space-y-8 text-center">
        <h1 className="text-3xl font-bold tracking-tighter bg-gradient-to-r from-purple-400 to-pink-600 bg-clip-text text-transparent">
          PARADOKS KIOSK
        </h1>
        
        {photoUrl ? (
          <div className="relative group">
            <div className="absolute -inset-1 bg-gradient-to-r from-purple-600 to-pink-600 rounded-2xl blur opacity-25 group-hover:opacity-50 transition duration-1000"></div>
            <img 
              src={photoUrl} 
              alt="AI Art" 
              className="relative rounded-xl shadow-2xl border border-white/10 w-full"
            />
          </div>
        ) : (
          <p className="text-zinc-500">Görsel bulunamadı veya yükleniyor...</p>
        )}

        <a 
          href={photoUrl} 
          download="ai_photo.jpg"
          className="block w-full py-4 bg-white text-black font-bold rounded-xl hover:bg-zinc-200 transition-transform active:scale-95 shadow-xl"
        >
          FOTOĞRAFI İNDİR
        </a>
        
        <p className="text-xs text-zinc-500 uppercase tracking-widest">
          AI ART GENERATION SYSTEM V1.0
        </p>
      </div>
    </div>
  );
}