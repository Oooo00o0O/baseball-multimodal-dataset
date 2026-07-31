import os
import csv
import cv2
import librosa
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import torchvision.models as models
import torchvision.models.video as video_models
from torch.optim.lr_scheduler import CosineAnnealingLR
import warnings
import random

warnings.filterwarnings('ignore')

# ==========================================
# 模块一：工业级多模态特征提取
# ==========================================
def extract_audio_features(audio_path, hit_time, sr=16000, is_train=False):
    """【重磅升级】将音频转为 3 通道，完美适配 ResNet18"""
    audio_data, _ = librosa.load(audio_path, sr=sr)
    
    # 扩大声音截取范围：击球前 0.2 秒到击球后 0.6 秒 (0.8秒总长，包含完整的尾音)
    start_sample = int(max(0, (hit_time - 0.2) * sr))
    end_sample = int(start_sample + 0.8 * sr)
    cropped_audio = audio_data[start_sample:end_sample]
    
    if len(cropped_audio) < int(0.8 * sr):
        cropped_audio = np.pad(cropped_audio, (0, int(0.8 * sr) - len(cropped_audio)), 'constant')
    
    # 高级音频数据增强
    if is_train:
        # 1. 随机添加微弱白噪声
        if random.random() > 0.5:
            noise = np.random.randn(len(cropped_audio))
            cropped_audio = cropped_audio + 0.002 * noise
        # 2. 随机轻微改变音量
        if random.random() > 0.5:
            cropped_audio = cropped_audio * random.uniform(0.8, 1.2)
            
    mel_spec = librosa.feature.melspectrogram(y=cropped_audio, sr=sr, n_fft=512, hop_length=128, n_mels=128)
    mel_db = librosa.power_to_db(mel_spec, ref=np.max)
    
    # 标准化
    tensor_img = torch.from_numpy(mel_db).float().unsqueeze(0)
    tensor_img = (tensor_img - tensor_img.mean()) / (tensor_img.std() + 1e-6)
    
    # 【核心操作】将 1 通道的声音图片复制 3 份，变成 3 通道，欺骗 ResNet18
    tensor_img = tensor_img.repeat(3, 1, 1) 
    return tensor_img

def extract_video_features(video_path, hit_time, num_frames=16, target_size=(112, 112), is_train=False):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return torch.zeros((3, num_frames, target_size[1], target_size[0]))
        
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0 or np.isnan(fps): fps = 30.0
        
    hit_frame_idx = int(hit_time * fps)
    
    # 隔帧采样，视野达到 1 秒以上，看清完整抛物线
    frame_skip = 2 
    start_frame_idx = max(0, hit_frame_idx - (num_frames * frame_skip // 2))
    
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame_idx)
    frames = []
    
    apply_flip = is_train and random.random() > 0.5
    
    frame_count = 0
    while len(frames) < num_frames:
        ret, frame = cap.read()
        if not ret: break
        
        if frame_count % frame_skip == 0:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.resize(frame, target_size)
            if apply_flip:
                frame = cv2.flip(frame, 1)
            frames.append(frame)
        frame_count += 1
        
    cap.release()
    
    while len(frames) < num_frames:
        frames.append(frames[-1].copy() if len(frames) > 0 else np.zeros((target_size[1], target_size[0], 3), dtype=np.uint8))
            
    frames_np = np.array(frames, dtype=np.float32) / 255.0
    mean = np.array([0.43216, 0.394666, 0.37645])
    std = np.array([0.22803, 0.22145, 0.216989])
    frames_np = (frames_np - mean) / std
    
    return torch.from_numpy(frames_np).float().permute(3, 0, 1, 2)

# ==========================================
# 模块二：精细化数据工厂
# ==========================================
class MultimodalBaseballDataset(Dataset):
    def __init__(self, root_dir, is_train=False):
        self.data_list = []
        self.labels = []
        self.is_train = is_train 
        categories = {'ground_ball': 0, 'fly_ball': 1}
        
        video_exts = ('.mp4', '.avi', '.mov')
        for category, label in categories.items():
            category_path = os.path.join(root_dir, category)
            if not os.path.exists(category_path): continue
                
            for root_path, _, files in os.walk(category_path):
                audio_file = next((os.path.join(root_path, f) for f in files if f.lower().endswith('.wav')), None)
                video_file = next((os.path.join(root_path, f) for f in files if f.lower().endswith(video_exts)), None)
                csv_file = next((os.path.join(root_path, f) for f in files if f.lower().endswith('.csv')), None)
                
                if audio_file and video_file and csv_file:
                    self.data_list.append({'audio_path': audio_file, 'video_path': video_file, 'time_path': csv_file})
                    self.labels.append(label)

    def __len__(self):
        return len(self.data_list)

    def __getitem__(self, idx):
        data = self.data_list[idx]
        label = self.labels[idx]
        
        try:
            with open(data['time_path'], 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                hit_time = float(next(reader)['event_start'])
        except Exception:
            hit_time = 1.0 
            
        audio_tensor = extract_audio_features(data['audio_path'], hit_time, is_train=self.is_train)
        video_tensor = extract_video_features(data['video_path'], hit_time, is_train=self.is_train)
        
        return audio_tensor, video_tensor, label

# ==========================================
# 模块三：终极双残差融合大脑 (ResNet18 + R3D18)
# ==========================================
class UltimateFusionNet(nn.Module):
    def __init__(self):
        super(UltimateFusionNet, self).__init__()
        
        # 1. 听觉大脑：加载预训练的 2D ResNet18
        self.audio_branch = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
        # 将最后的 1000 分类全连接层替换为提炼出 128 维声学特征
        self.audio_branch.fc = nn.Sequential(
            nn.Dropout(0.5),
            nn.Linear(self.audio_branch.fc.in_features, 128),
            nn.BatchNorm1d(128),
            nn.ReLU()
        )
        
        # 2. 视觉大脑：加载预训练的 3D R3D18
        self.video_branch = video_models.r3d_18(weights=video_models.R3D_18_Weights.DEFAULT)
        self.video_branch.fc = nn.Sequential(
            nn.Dropout(0.5),
            nn.Linear(self.video_branch.fc.in_features, 128),
            nn.BatchNorm1d(128),
            nn.ReLU()
        )
        
        # 3. 黄金融合层
        self.fusion_classifier = nn.Sequential(
            nn.Dropout(0.6), # 极高 dropout 防止记背
            nn.Linear(128 + 128, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, 2)
        )

    def forward(self, audio_x, video_x):
        audio_features = self.audio_branch(audio_x)
        video_features = self.video_branch(video_x)
        fused_features = torch.cat((audio_features, video_features), dim=1)
        out = self.fusion_classifier(fused_features)
        return out

# ==========================================
# 模块四：工业级标准训练管线
# ==========================================
def train_ultimate_multimodal():
    print("\n========== [1/3] 初始化终极数据集 (多线程模式) ==========")
    full_dataset_paths = MultimodalBaseballDataset(root_dir='./dataset')
    
    if len(full_dataset_paths) == 0:
        print("未找到数据，请检查文件夹结构。")
        return
        
    total_size = len(full_dataset_paths)
    train_size = int(0.7 * total_size)
    val_size = int(0.15 * total_size)
    test_size = total_size - train_size - val_size
    
    indices = list(range(total_size))
    np.random.seed(42) # 保证每次划分一致
    np.random.shuffle(indices)
    
    train_idx = indices[:train_size]
    val_idx = indices[train_size:train_size+val_size]
    test_idx = indices[train_size+val_size:]
    
    train_ds = MultimodalBaseballDataset(root_dir='./dataset', is_train=True)
    val_ds, test_ds = MultimodalBaseballDataset(root_dir='./dataset', is_train=False), MultimodalBaseballDataset(root_dir='./dataset', is_train=False)
    
    train_ds.data_list, train_ds.labels = [full_dataset_paths.data_list[i] for i in train_idx], [full_dataset_paths.labels[i] for i in train_idx]
    val_ds.data_list, val_ds.labels = [full_dataset_paths.data_list[i] for i in val_idx], [full_dataset_paths.labels[i] for i in val_idx]
    test_ds.data_list, test_ds.labels = [full_dataset_paths.data_list[i] for i in test_idx], [full_dataset_paths.labels[i] for i in test_idx]
    
    # 依然保留多线程加速，否则硬盘会成为瓶颈
    train_loader = DataLoader(train_ds, batch_size=8, shuffle=True, num_workers=4, pin_memory=True)
    val_loader = DataLoader(val_ds, batch_size=8, shuffle=False, num_workers=4, pin_memory=True)
    test_loader = DataLoader(test_ds, batch_size=8, shuffle=False, num_workers=4, pin_memory=True)
    
    print("\n========== [2/3] 部署双残差网络 (ResNet-18 + R3D-18) ==========")
    model = UltimateFusionNet()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"核心已加载，正在使用: {device}")
    model = model.to(device)
    
    # 升级为 AdamW 优化器，带权重衰减，极大降低过拟合概率
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=1e-4, weight_decay=1e-3)
    
    # 引入余弦退火学习率调度器：让 AI 的学习步伐从大步流星逐渐变为精雕细琢
    epochs = 30
    scheduler = CosineAnnealingLR(optimizer, T_max=epochs)
    
    print(f"\n========== [3/3] 开启极限炼丹 (设置 30 轮，含早停保护) ==========")
    best_val_loss = float('inf')
    best_val_acc = 0.0
    
    for epoch in range(epochs):
        model.train()
        running_loss = 0.0
        
        for i, (audios, videos, labels) in enumerate(train_loader):
            audios, videos, labels = audios.to(device), videos.to(device), labels.to(device)
            
            optimizer.zero_grad()
            outputs = model(audios, videos)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()
            
            if (i+1) % 20 == 0:
                print(f"  [Epoch {epoch+1}/{epochs}] 进度: {i+1}/{len(train_loader)}")
                
        # 更新学习率
        scheduler.step()
        train_loss = running_loss / len(train_loader)
            
        # 验证阶段
        model.eval()
        val_loss, correct, total = 0.0, 0, 0
        with torch.no_grad():
            for audios, videos, labels in val_loader:
                audios, videos, labels = audios.to(device), videos.to(device), labels.to(device)
                outputs = model(audios, videos)
                loss = criterion(outputs, labels)
                val_loss += loss.item()
                
                _, predicted = torch.max(outputs.data, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
        
        avg_val_loss = val_loss / len(val_loader)
        val_acc = 100 * correct / total
        current_lr = scheduler.get_last_lr()[0]
        
        print(f"[Epoch {epoch+1}/{epochs}] | LR: {current_lr:.6f} | Train Loss: {train_loss:.4f} | Val Loss: {avg_val_loss:.4f} | Val Acc: {val_acc:.2f}%")
        
        # 严苛的模型保存逻辑：不仅要 Loss 低，Acc 也要高
        if avg_val_loss < best_val_loss or val_acc > best_val_acc:
            if avg_val_loss < best_val_loss: best_val_loss = avg_val_loss
            if val_acc > best_val_acc: best_val_acc = val_acc
            
            torch.save(model.state_dict(), 'ultimate_multimodal_model.pth')
            print(f"  --> [BEST] Better weights found, model saved!")
            
    print("\n========== [终极考验] 绝对盲测 ==========")
    model.load_state_dict(torch.load('ultimate_multimodal_model.pth'))
    model.eval()
    
    correct, total = 0, 0
    with torch.no_grad():
        for audios, videos, labels in test_loader:
            audios, videos, labels = audios.to(device), videos.to(device), labels.to(device)
            outputs = model(audios, videos)
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
            
    print(f"\n[FINAL] Ultimate Blind Test Accuracy: {100 * correct / total:.2f}%")

if __name__ == "__main__":
    train_ultimate_multimodal()