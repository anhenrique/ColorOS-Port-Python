import sys

print("🔍 Analisando os primeiros megabytes da imagem RAW...")
try:
    with open("temp_samsung/super.raw.img", "rb") as f:
        data = f.read(1024 * 1024 * 5) # Lendo os primeiros 5MB
        
    offsets = []
    idx = data.find(b"0PLA") # "0PLA" é a assinatura de partições dinâmicas
    
    while idx != -1:
        offsets.append(idx)
        idx = data.find(b"0PLA", idx + 4)
        
    if offsets:
        print(f"✅ SUCESSO! Tabela de partições encontrada nos offsets: {offsets}")
        if 4096 not in offsets:
            print("⚠️ AVISO: O cabeçalho não está no local padrão (4096). É por isso que o lpunpack falhou!")
    else:
        print("❌ ERRO: Tabela de partições não encontrada! A Samsung usou outro formato de encapsulamento.")
except Exception as e:
    print(f"Erro ao ler o arquivo: {e}")
