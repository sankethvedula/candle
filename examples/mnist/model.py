import argparse
import io
import os
import random

from PIL import Image
from torch.autograd import Variable
from torch.optim.lr_scheduler import ExponentialLR
import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.data as data

import candle

class SerializableModule(nn.Module):
    def __init__(self):
        super().__init__()

    def save(self, filename):
        torch.save(self.state_dict(), filename)

    def load(self, filename):
        self.load_state_dict(torch.load(filename, map_location=lambda storage, loc: storage))

def read_idx(bytes):
    reader = io.BytesIO(bytes)
    reader.read(3)
    n_dims = int.from_bytes(reader.read(1), byteorder="big")
    sizes = []
    for _ in range(n_dims):
        sizes.append(int.from_bytes(reader.read(4), byteorder="big"))
    size = int(np.prod(sizes))
    buf = reader.read(size)
    return np.frombuffer(buf, dtype=np.uint8).reshape(sizes)

class SingleMnistDataset(data.Dataset):
    def __init__(self, images, labels, is_training):
        self.clean_images = []
        self.clean_labels = []
        for image, label in zip(images, labels):
            image = np.transpose(image)
            self.clean_images.append(Image.fromarray(image))
            self.clean_labels.append(int(label))
        self.is_training = is_training

    @classmethod
    def splits(cls, config, **kwargs):
        data_dir = config.dir
        img_files = [os.path.join(data_dir, "train-images-idx3-ubyte"),
            os.path.join(data_dir, "t10k-images-idx3-ubyte")]
        image_sets = []
        for image_set in img_files:
            with open(image_set, "rb") as f:
                content = f.read()
            arr = read_idx(content)
            image_sets.append(arr)

        lbl_files = [os.path.join(data_dir, "train-labels-idx1-ubyte"),
            os.path.join(data_dir, "t10k-labels-idx1-ubyte")]
        lbl_sets = []
        for lbl_set in lbl_files:
            with open(lbl_set, "rb") as f:
                content = f.read()
            lbl_sets.append(read_idx(content).astype(np.int))

        dev_images = image_sets[0][-2500:]
        image_sets[0] = image_sets[0][:-2500]
        image_sets.append(dev_images)
        dev_lbls = lbl_sets[0][-2500:]
        lbl_sets[0] = lbl_sets[0][:-2500]
        lbl_sets.append(dev_lbls)
        return cls(image_sets[0], lbl_sets[0], True, **kwargs), cls(image_sets[2], lbl_sets[2], False, **kwargs), \
            cls(image_sets[1], lbl_sets[1], False, **kwargs)

    def __getitem__(self, index):
        lbl = self.clean_labels[index]
        img = self.clean_images[index]
        arr = np.array(img)
        arr = arr.astype(np.float32)
        arr = (arr / 255) * 2 - 1
        return torch.from_numpy(arr), lbl

    def __len__(self):
        return len(self.clean_images)

class DNNModel(SerializableModule):
    def __init__(self):
        super().__init__()
        self.use_cuda = True
        def make_hidden(n_in, n_out, dropout=0.5):
            return nn.Sequential(
                ctx.binarized(nn.Linear(n_in, n_out)),
                nn.BatchNorm1d(n_out),
                candle.BinaryTanh(),
                nn.Dropout(dropout))
        ctx = candle.Context(candle.read_config())
        n_units = 4096
        mod_list = [make_hidden(784, n_units, dropout=0.2)]
        mod_list.extend(make_hidden(n_units, n_units) for _ in range(3))
        mod_list.append(ctx.binarized(nn.Linear(n_units, 10)))
        self.layers = nn.ModuleList(mod_list)

    def forward(self, x):
        x = x.view(x.size(0), -1)
        for l in self.layers:
            x = l(x)
        return x

class ConvModel(SerializableModule):
    def __init__(self):
        super().__init__()
        self.use_cuda = True
        ctx = candle.Context(candle.read_config())
        self.conv1 = ctx.binarized(nn.Conv2d(1, 64, 5))
        self.bn1 = nn.BatchNorm2d(64, affine=True)
        self.conv2 = ctx.binarized(nn.Conv2d(64, 96, 5))
        self.bn2 = nn.BatchNorm2d(96, affine=True)
        self.pool = nn.MaxPool2d(2)
        self.dropout = nn.Dropout(0.6)
        self.bn3 = nn.BatchNorm1d(16 * 96)
        self.fc1 = ctx.binarized(nn.Linear(16 * 96, 1024))
        self.bn4 = nn.BatchNorm1d(1024)
        self.fc2 = ctx.binarized(nn.Linear(1024, 10))

    def encode(self, x):
        x = x.unsqueeze(1)
        x = self.pool(self.bn1(candle.binary_tanh(self.conv1(x))))
        x = self.pool(self.bn2(candle.binary_tanh(self.conv2(x))))
        return x

    def forward(self, x):
        x = self.encode(x)
        x = x.view(x.size(0), -1)
        x = self.bn3(x)
        x = self.dropout(candle.binary_tanh(self.fc1(x)))
        x = self.bn4(x)
        return self.fc2(x)

class TinyModel(SerializableModule):
    def __init__(self):
        super().__init__()
        self.use_cuda = True
        ctx = candle.Context(candle.read_config())
        self.conv1 = ctx.binarized(nn.Conv2d(1, 17, 5))
        self.bn1 = nn.BatchNorm2d(17, affine=False)
        self.conv2 = ctx.binarized(nn.Conv2d(17, 10, 3))
        self.bn2 = nn.BatchNorm2d(10, affine=False)
        self.pool = nn.MaxPool2d(3)
        self.fc = nn.Linear(40, 10)

    def forward(self, x):
        x = x.unsqueeze(1)
        x = self.pool(self.bn1(F.relu(self.conv1(x))))
        x = self.pool(self.bn2(F.relu(self.conv2(x))))
        x = x.view(x.size(0), -1)
        return self.fc(x.view(x.size(0), -1))

def train(args):
    params = candle.list_params(model, train_prune=False)
    optimizer = torch.optim.Adam(params, lr=3E-4, weight_decay=0.0005)
    criterion = nn.MultiMarginLoss(p=2)

    train_set, dev_set, test_set = SingleMnistDataset.splits(args)
    train_loader = data.DataLoader(train_set, batch_size=100, shuffle=True, drop_last=True)
    dev_loader = data.DataLoader(dev_set, batch_size=min(32, len(dev_set)))
    test_loader = data.DataLoader(test_set, batch_size=min(32, len(test_set)))
    lr_start = 3E-4
    lr_fin = 1E-5
    if args.n_epochs > 0:
        lr_scheduler = ExponentialLR(optimizer, (lr_fin / lr_start)**(1 / args.n_epochs))

    best_dev = -np.inf

    for n_epoch in range(args.n_epochs):
        print("Epoch: {}".format(n_epoch + 1))
        for i, (model_in, labels) in enumerate(train_loader):
            model.train()
            optimizer.zero_grad()

            model_in = Variable(model_in.cuda(), requires_grad=False)
            labels = Variable(labels.cuda(), requires_grad=False)
            scores = model(model_in)
            loss = criterion(scores, labels)
            loss.backward()
            candle.update_all(model)
            candle.scale_all_lr(model)
            optimizer.step()
            candle.clip_all_binary(model)
            if i % 16 == 0:
                # n_unpruned = candle.count_params(model, type="unpruned")
                # if n_unpruned...:
                #     candle.prune_all(model, percentage=scheduler.compute_rate())
                accuracy = (torch.max(scores, 1)[1].view(model_in.size(0)).data == labels.data).sum() / model_in.size(0)
                print("train accuracy: {:>10}, loss: {:>25}".format(accuracy, loss.data[0]))
        accuracy = 0
        n = 0
        model.eval()
        for model_in, labels in dev_loader:
            model_in = Variable(model_in.cuda(), volatile=True)
            labels = Variable(labels.cuda(), volatile=True)
            scores = model(model_in)
            accuracy += (torch.max(scores, 1)[1].view(model_in.size(0)).data == labels.data).sum()
            n += model_in.size(0)
        print("dev accuracy: {:>10}".format(accuracy / n))
        lr_scheduler.step()
        if accuracy > best_dev:
            best_dev = accuracy
            print("Saving best model...")
            model.save(args.out_file)

    model.eval()
    n = 0
    accuracy = 0
    for model_in, labels in test_loader:
        model_in = Variable(model_in.cuda(), volatile=True)
        labels = Variable(labels.cuda(), volatile=True)
        scores = model(model_in)
        accuracy += (torch.max(scores, 1)[1].view(model_in.size(0)).data == labels.data).sum()
        n += model_in.size(0)
    print("test accuracy: {:>10}".format(accuracy / n))
    model.save(args.out_file)

def init_model(input_file=None, use_cuda=True):
    global model
    model = ConvModel()
    model.cuda()
    if input_file:
        model.load(input_file)
    model.eval()

model = None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base_in_file", type=str, default="")
    parser.add_argument("--dir", type=str, default="local_data")
    parser.add_argument("--in_file", type=str, default="")
    parser.add_argument("--out_file", type=str, default="output.pt")
    parser.add_argument("--n_epochs", type=int, default=40)
    args, _ = parser.parse_known_args()
    global model
    init_model(input_file=args.in_file)
    train(args)

if __name__ == "__main__":
    main()