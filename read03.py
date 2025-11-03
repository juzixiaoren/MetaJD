import numpy as np
import torch
import pandas as pd
import os
import torch.nn as nn
import torch.nn.functional as F
import gc

class UltraLightDataLoader:
    def __init__(self, data_path):
        self.data_path = data_path
        
    def load_npz_data(self):
        """加载npz格式数据，内存优化版本"""
        print("正在加载数据...")
        data = np.load(self.data_path)
        
        # 分批加载大数组，避免一次性占用太多内存
        data_dict = {}
        for key in data.files:
            print(f"加载 {key}...")
            data_dict[key] = data[key]
            # 立即释放numpy数组的引用
            if hasattr(data[key], 'nbytes'):
                print(f"  {key} 大小: {data[key].nbytes / 1024 / 1024:.2f} MB")
        
        print("数据统计信息:")
        print(f"节点数量: {data_dict['x'].shape[0]}")
        print(f"节点特征维度: {data_dict['x'].shape[1]}")
        print(f"边数量: {data_dict['edge_index'].shape[0]}")
        
        return data_dict
    
    def create_data_dict(self):
        """创建数据字典，内存优化版本"""
        raw_data = self.load_npz_data()
        
        # 快速处理数据类型
        if raw_data['train_mask'].dtype != bool:
            raw_data['train_mask'] = raw_data['train_mask'].astype(bool)
        if raw_data['test_mask'].dtype != bool:
            raw_data['test_mask'] = raw_data['test_mask'].astype(bool)
        
        # 处理节点特征 - 使用更小的数据类型
        print("处理节点特征...")
        x = torch.FloatTensor(raw_data['x'].astype(np.float32))
        
        # 处理边数据
        edge_index = torch.LongTensor(raw_data['edge_index'].T.astype(np.int32))
        
        # 只保留必要的标签和掩码
        y = torch.LongTensor(raw_data['y'].astype(np.int32))
        train_mask = torch.BoolTensor(raw_data['train_mask'])
        test_mask = torch.BoolTensor(raw_data['test_mask'])
        
        # 简化前景节点掩码
        foreground_mask = ((y == 0) | (y == 1))
        
        print(f"前景节点数量: {foreground_mask.sum().item()}")
        
        # 创建最小数据字典
        data_dict = {
            'x': x,
            'edge_index': edge_index,
            'y': y,
            'train_mask': train_mask,
            'test_mask': test_mask,
            'foreground_mask': foreground_mask,
            'num_nodes': x.shape[0],
        }
        
        # 强制垃圾回收
        del raw_data
        gc.collect()
        
        return data_dict

class MinimalFeatureExtractor:
    """最小特征提取器"""
    def __init__(self, data_dict):
        self.data_dict = data_dict
        
    def compute_minimal_features(self):
        """只计算最必要的特征"""
        edge_index = self.data_dict['edge_index']
        num_nodes = self.data_dict['num_nodes']
        
        print("计算最小图特征...")
        
        # 只计算节点度（最重要的特征）
        src_nodes = edge_index[0]
        degrees = torch.bincount(src_nodes, minlength=num_nodes).float()
        
        # 归一化节点度
        degrees_normalized = degrees / (degrees.max() + 1e-8)
        
        # 只保留节点度特征
        graph_features = degrees_normalized.unsqueeze(1)
        
        return graph_features
    
    def extract_features(self):
        """提取特征"""
        print("开始特征工程...")
        
        # 图特征
        graph_features = self.compute_minimal_features()
        print(f"图特征维度: {graph_features.shape}")
        
        # 原始特征降维 - 只取前N个重要特征
        original_features = self.data_dict['x']
        max_features = min(32, original_features.shape[1])  # 限制特征数量
        original_features_reduced = original_features[:, :max_features]
        
        print(f"降维后原始特征: {original_features_reduced.shape}")
        
        # 合并特征
        all_features = torch.cat([original_features_reduced, graph_features], dim=1)
        
        print(f"最终特征维度: {all_features.shape}")
        
        # 更新数据字典
        self.data_dict['x'] = all_features
        self.data_dict['feature_dim'] = all_features.shape[1]
        
        return all_features

class MicroGNNLayer(nn.Module):
    """微型图神经网络层"""
    def __init__(self, in_channels, out_channels):
        super(MicroGNNLayer, self).__init__()
        self.linear = nn.Linear(in_channels, out_channels)
        
    def forward(self, x, edge_index):
        src, dst = edge_index
        
        # 极简消息传递：只聚合直接邻居
        message = torch.zeros_like(x)
        
        # 小批量处理边，避免内存爆炸
        batch_size = 10000  # 小批量大小
        for i in range(0, len(src), batch_size):
            end_idx = min(i + batch_size, len(src))
            batch_src = src[i:end_idx]
            batch_dst = dst[i:end_idx]
            
            # 累加邻居信息
            for j in range(len(batch_src)):
                message[batch_dst[j]] += x[batch_src[j]]
        
        # 简单的特征组合
        combined = x + 0.1 * message  # 小权重避免数值爆炸
        output = self.linear(combined)
        output = F.relu(output)
        
        return output

class MicroFraudDetector(nn.Module):
    """微型反欺诈检测模型"""
    def __init__(self, node_dim, hidden_dim=64, dropout=0.2):
        super(MicroFraudDetector, self).__init__()
        
        # 极简模型结构
        self.layers = nn.Sequential(
            nn.Linear(node_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(), 
            nn.Dropout(dropout),
            nn.Linear(hidden_dim // 2, 2)  # 二分类输出
        )
        
    def forward(self, x, edge_index=None, edge_attr=None):
        # 如果提供了边信息，进行简单的图传播
        if edge_index is not None:
            # 单层轻量图传播
            src, dst = edge_index
            message = torch.zeros_like(x)
            
            # 小批量处理
            batch_size = 5000
            for i in range(0, len(src), batch_size):
                end_idx = min(i + batch_size, len(src))
                batch_src = src[i:end_idx]
                batch_dst = dst[i:end_idx]
                
                for j in range(len(batch_src)):
                    message[batch_dst[j]] += x[batch_src[j]]
            
            # 结合图信息
            x = x + 0.05 * message
        
        # 分类
        out = self.layers(x)
        
        return out

class MemoryEfficientTrainer:
    def __init__(self, model, data_dict, device):
        self.model = model.to(device)
        self.data_dict = data_dict
        self.device = device
        
        # 分批加载数据到设备
        print("分批加载数据到设备...")
        self.x = data_dict['x'].to(device)
        self.y = data_dict['y'].to(device)
        
        # 边数据保持在CPU，使用时再移动到GPU
        self.edge_index = data_dict['edge_index']
        
        self.criterion = nn.CrossEntropyLoss()  # 使用简单损失函数
        self.optimizer = torch.optim.Adam(model.parameters(), lr=0.001, weight_decay=1e-4)
        
        self.train_losses = []
        
    def train_epoch(self, epoch):
        """训练一个epoch，内存优化"""
        self.model.train()
        self.optimizer.zero_grad()
        
        # 小批量处理边数据
        edge_index_batch = self.edge_index.to(self.device)
        
        # 前向传播
        out = self.model(self.x, edge_index_batch)
        
        # 只对训练集的前景节点计算损失
        train_foreground = self.data_dict['train_mask'] & self.data_dict['foreground_mask']
        train_labels = self.y[train_foreground]
        train_preds = out[train_foreground]
        
        loss = self.criterion(train_preds, train_labels)
        
        # 反向传播
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
        self.optimizer.step()
        
        # 立即从GPU移除边数据
        del edge_index_batch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        return loss.item()
    
    def evaluate(self):
        """评估模型，内存优化"""
        self.model.eval()
        
        with torch.no_grad():
            # 小批量处理边数据
            edge_index_batch = self.edge_index.to(self.device)
            
            out = self.model(self.x, edge_index_batch)
            
            test_foreground = self.data_dict['test_mask'] & self.data_dict['foreground_mask']
            labels = self.y[test_foreground].cpu().numpy()
            preds = torch.softmax(out[test_foreground], dim=1)[:, 1].cpu().numpy()
            
            # 清理
            del edge_index_batch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        
        return preds, labels
    
    def train(self, epochs=20):
        """极简训练过程"""
        print("开始极简训练...")
        
        best_loss = float('inf')
        patience = 5
        patience_counter = 0
        
        for epoch in range(epochs):
            # 训练
            train_loss = self.train_epoch(epoch)
            self.train_losses.append(train_loss)
            
            # 每5个epoch输出一次
            if epoch % 5 == 0 or epoch == epochs - 1:
                print(f"Epoch {epoch:03d}: Loss: {train_loss:.4f}")
                
                # 简单早停
                if train_loss < best_loss:
                    best_loss = train_loss
                    patience_counter = 0
                    torch.save(self.model.state_dict(), 'micro_model.pth')
                else:
                    patience_counter += 1
                
                if patience_counter >= patience:
                    print(f"早停在epoch {epoch}")
                    break
            
            # 强制垃圾回收
            if epoch % 10 == 0:
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
        
        # 加载最佳模型
        if os.path.exists('micro_model.pth'):
            self.model.load_state_dict(torch.load('micro_model.pth'))
        
        return self.train_losses

def compute_basic_metrics(preds, labels):
    """基础评估指标"""
    if torch.is_tensor(preds):
        preds = preds.cpu().numpy()
    if torch.is_tensor(labels):
        labels = labels.cpu().numpy()
    
    # 简单AUC计算
    sorted_indices = np.argsort(preds)[::-1]
    sorted_labels = labels[sorted_indices]
    
    total_pos = np.sum(labels == 1)
    total_neg = np.sum(labels == 0)
    
    if total_pos == 0 or total_neg == 0:
        auc_roc = 0.5
    else:
        tpr, fpr = [0], [0]
        tp, fp = 0, 0
        
        for label in sorted_labels:
            if label == 1:
                tp += 1
            else:
                fp += 1
            tpr.append(tp / total_pos)
            fpr.append(fp / total_neg)
        
        auc_roc = np.trapz(tpr, fpr)
    
    # 基础F1
    pred_binary = (preds > 0.5).astype(int)
    tp = np.sum((pred_binary == 1) & (labels == 1))
    fp = np.sum((pred_binary == 1) & (labels == 0))
    fn = np.sum((pred_binary == 0) & (labels == 1))
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    return {'auc_roc': auc_roc, 'f1_score': f1, 'precision': precision, 'recall': recall}

def micro_training_pipeline():
    """微型训练流程"""
    # 设置设备
    device = torch.device('cuda' if torch.cuda.is_available() and torch.cuda.memory_allocated() < 2e9 else 'cpu')
    print(f"使用设备: {device}")
    
    # 监控内存
    if device.type == 'cuda':
        print(f"GPU内存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
    
    try:
        # 1. 加载数据
        print("=== 步骤1: 加载数据 ===")
        data_path = "phase1_gdata.npz"
        if not os.path.exists(data_path):
            # 尝试其他路径
            data_path = "phase1\\phase1\\phase1_gdata.npz"
            if not os.path.exists(data_path):
                data_path = "phase1/phase1/phase1_gdata.npz"
        
        data_loader = UltraLightDataLoader(data_path)
        data_dict = data_loader.create_data_dict()
        
        # 2. 最小特征工程
        print("\n=== 步骤2: 特征工程 ===")
        feature_extractor = MinimalFeatureExtractor(data_dict)
        features = feature_extractor.extract_features()
        
        # 3. 初始化微型模型
        print("\n=== 步骤3: 初始化模型 ===")
        node_dim = data_dict['feature_dim']
        model = MicroFraudDetector(
            node_dim=node_dim,
            hidden_dim=32,  # 极小的隐藏层
            dropout=0.1
        )
        
        print(f"模型参数量: {sum(p.numel() for p in model.parameters()):,}")
        
        # 4. 内存优化训练
        print("\n=== 步骤4: 模型训练 ===")
        trainer = MemoryEfficientTrainer(model, data_dict, device)
        train_losses = trainer.train(epochs=15)  # 很少的训练轮次
        
        # 5. 最终评估
        print("\n=== 步骤5: 最终评估 ===")
        test_preds, test_labels = trainer.evaluate()
        test_metrics = compute_basic_metrics(test_preds, test_labels)
        
        print(f"测试集结果:")
        print(f"AUC-ROC: {test_metrics['auc_roc']:.4f}")
        print(f"F1-Score: {test_metrics['f1_score']:.4f}")
        
        # 6. 生成提交文件
        print("\n=== 步骤6: 生成提交文件 ===")
        model.eval()
        with torch.no_grad():
            edge_index_batch = data_dict['edge_index'].to(device)
            out = model(data_dict['x'].to(device), edge_index_batch)
            
            test_foreground = data_dict['test_mask'] & data_dict['foreground_mask']
            test_preds = torch.softmax(out[test_foreground], dim=1).cpu().numpy()
            
            submission_df = pd.DataFrame(test_preds, columns=['prob_0', 'prob_1'])
            submission_df.to_csv('micro_submission.csv', index=False)
            
            print(f"提交文件已保存: micro_submission.csv")
            print(f"提交文件形状: {test_preds.shape}")
        
        return model, test_metrics, test_preds
        
    except Exception as e:
        print(f"微型训练失败: {e}")
        return None, None, None

def create_ultra_light_submission():
    """创建超轻量提交文件（最后备选）"""
    print("创建超轻量提交文件...")
    
    try:
        # 加载最小数据
        data_path = "phase1_gdata.npz"
        if not os.path.exists(data_path):
            data_path = "phase1/phase1_gdata.npz"
            if not os.path.exists(data_path):
                data_path = "phase1/phase1/phase1_gdata.npz"
        
        data = np.load(data_path)
        test_mask = data['test_mask']
        y = data['y']
        
        # 创建简单预测（基于先验分布）
        foreground_test = test_mask & ((y == 0) | (y == 1))
        num_test_samples = foreground_test.sum()
        
        # 简单预测：假设90%正常，10%欺诈
        preds = np.array([[0.9, 0.1]] * num_test_samples, dtype=np.float32)
        
        submission_df = pd.DataFrame(preds, columns=['prob_0', 'prob_1'])
        submission_df.to_csv('ultralight_submission.csv', index=False)
        
        print(f"超轻量提交文件已生成: ultralight_submission.csv")
        print(f"提交文件形状: {preds.shape}")
        
        return preds
        
    except Exception as e:
        print(f"超轻量提交失败: {e}")
        # 最终备选：创建默认文件
        default_preds = np.array([[0.8, 0.2]] * 1000, dtype=np.float32)
        pd.DataFrame(default_preds, columns=['prob_0', 'prob_1']).to_csv('final_submission.csv', index=False)
        print("最终备选提交文件已生成: final_submission.csv")
        return default_preds

if __name__ == "__main__":
    print("=" * 60)
    print("内存优化版反欺诈检测模型")
    print("=" * 60)
    
    # 显示内存信息
    import psutil
    memory = psutil.virtual_memory()
    print(f"系统内存: {memory.available / 1024**3:.1f} GB 可用 / {memory.total / 1024**3:.1f} GB 总量")
    
    if torch.cuda.is_available():
        print(f"GPU内存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
    
    # 尝试微型训练
    print("\n尝试微型训练流程...")
    model, metrics, submission = micro_training_pipeline()
    
    if model is None:
        print("\n微型训练失败，创建超轻量提交文件...")
        submission = create_ultra_light_submission()
        metrics = {'auc_roc': 0.5, 'f1_score': 0.0}
    
    print("\n" + "=" * 60)
    print("程序执行完成！")
    print("生成的提交文件:")
    files = ['micro_submission.csv', 'ultralight_submission.csv', 'final_submission.csv']
    for file in files:
        if os.path.exists(file):
            print(f"- {file}")
    print("=" * 60)