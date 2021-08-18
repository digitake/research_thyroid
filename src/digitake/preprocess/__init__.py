import os
import torchvision.transforms as transforms
import glob
from PIL import Image
from torch.utils.data import Dataset
from torch.utils.data.dataset import T_co
from torchvision.transforms.functional import InterpolationMode
from typing import Dict

# imagenet mean and std
imagenet_mean = [0.485, 0.456, 0.406]
imagenet_std = [0.229, 0.224, 0.225]


##################################
# transform in dataset to target size
##################################
def get_transform(target_size, phase='train'):
    """
    Pre-defined transformation pipe for the dataset
    :param target_size: tuple of (W,H) result image from the pipe
    :param phase: train/val/test phase of different transformation e.g. test will not need RandomCrop
    :return: a transformation function to target_size
    """

    # enlarge 10% bigger for the later cropping
    enlarge = transforms.Resize(size=(int(target_size[0] * 1.1), int(target_size[1] * 1.1)))

    # ImageNet normalizer
    imagenet_normalize = transforms.Normalize(mean=imagenet_mean, std=imagenet_std)

    transform_dict = {
        'train':
            transforms.Compose([
                enlarge,
                transforms.RandomRotation(45, interpolation=InterpolationMode.BILINEAR, expand=True),
                transforms.CenterCrop(target_size),
                transforms.RandomHorizontalFlip(0.5),
                transforms.RandomPerspective(0.2),
                transforms.RandomApply([
                    transforms.ColorJitter(brightness=0.126, contrast=0.2)
                ], p=0.5),
                transforms.ToTensor(),
                imagenet_normalize
            ]),
        'val':
            transforms.Compose([
                enlarge,
                transforms.CenterCrop(target_size),
                transforms.ToTensor(),
                imagenet_normalize
            ]),
        'test':
            transforms.Compose([
                enlarge,
                transforms.CenterCrop(target_size),
                transforms.ToTensor(),
                imagenet_normalize
            ])
    }

    if phase in transform_dict:
        return transform_dict[phase]
    else:
        raise Exception("Unknown pharse specified")


def build_dataset(datasource: Dict[str, str], root="", ext="*.png"):
    """
    Build dataset by consuming data from root/<datasource-key>

    :param datasource: the datasource dictionary that maps from label to path
    eg. datasource = {
        'malignant': 'Malignant_Markers_Crop',
        'benign': 'Benign_Markers_Crop'
    }
    :param root: the root path to be prepended to datasource-key, default is emptu
    :param ext: the file extension to search for
    :return: a dictionary of data split by corresponding label name e.g. { 'benign', 'malignant'}
    """
    datasets = {}
    for key in datasource:
        datasets[key] = glob.glob(os.path.join(root, datasource[key], ext))

    return datasets


def explain_dataset(ds):
    total_dataitem = 0
    for key in ds:
        path_count = len(ds[key])
        total_dataitem += path_count
        print(f'Found total {path_count} for {key}')
    print(f"Total dataitem: {total_dataitem}")


def build_train_validation_set(datasource, val_size, root="", ext="*.png"):
    """
    :param datasource: dictionary with key as label of data, and value is a list of image path
    :param val_size: validation size, must be greater than total datasource size of each class's dataset
    :param root: the root path to be prepended to datasource, default is emptu
    :param ext: the file extension to search for
    :return a dictionary of data split by corresponding class name e.g. { 'benign', 'malignant'}
    """
    datasets = build_dataset(datasource, root=root, ext=ext)

    training_set = {}
    validation_set = {}
    total_training_set = 0
    total_validation_set = 0

    print("--" * 25)

    total_dataset = 0
    for key in datasets:    # for each class
        ds_size = len(datasets[key])  # size of each dataset
        total_dataset += ds_size

        assert val_size < ds_size, f"The size of dataset '{key}'({ds_size}) is smaller than validation size({val_size})"
        training_set[key] = datasets[key][val_size:]  # Cut from val_size-th onward
        t_size = len(training_set[key])
        total_training_set += t_size
        print(f'Total train {key} size = {t_size}/{ds_size} ({t_size / ds_size:0.2f})')

        validation_set[key] = datasets[key][:val_size]  # Validation data is the first n elements from the dataset
        v_size = len(validation_set[key])
        total_validation_set += v_size
        print(f'Total validation {key} size = {v_size}/{ds_size} ({v_size / ds_size:0.2f})')

    print("--" * 25)
    print(f"Total dataset size = {total_dataset}")

    return training_set, validation_set


class ThyroidDataset(Dataset):
    """
    Dataset for Thyroid Image
    """
    datasource_root = 'thyroid-ds3'  # base path to be prepend to each data source
    datasource_paths = {
        'malignant': 'Malignant_Markers_Crop',
        'benign': 'Benign_Markers_Crop'
    }

    training_params = {
        'val_size': 24,
        'test_size': 24
    }

    def __init__(self, phase, target_size, transform=None):
        self.phase = phase
        train, val = build_train_validation_set(
            ThyroidDataset.datasource_paths,
            val_size=ThyroidDataset.training_params['val_size'],
            root=ThyroidDataset.datasource_root
        )
        dataset = None

        if phase == 'train':
            dataset = train  # sum(train.values(), [])  # monoid flatten
        elif phase == 'val':
            dataset = val
        elif phase == 'test':
            dataset = val
        else:
            print("Custom phase is specified, please call set_dataset before start.")

        if dataset:
            self.set_dataset(dataset)

        if type(target_size) is int:
            target_size = (target_size, target_size)

        assert type(target_size) is tuple, "target_size must be tuple of (W:int, H:int) or int if square is needed"

        if transform:
            self.transform = transform
        else:
            self.transform = get_transform(target_size, phase)

    def set_dataset(self, dataset):
        self.dataset = dataset
        # Create a partition indices
        self.partition = [(k, len(v)) for k, v in sorted(self.dataset.items())]

    def __len__(self):
        size = len(sum(self.dataset.values(), []))  # monoid flatten, it's counting item so order doesn't matter
        return size

    def __get_partitioned_index(self, index):
        if index < 0:
            raise IndexError(f"Index must not be negative")

        class_num = 0
        for (k, v) in self.partition:
            if index >= v:
                index -= v
                class_num += 1
            else:
                return k, class_num, index
        raise IndexError(f"Index is out of range {index}")

    def __getitem__(self, index) -> T_co:
        """
        getitem takes index of linear data, meaning that the label key will be used to keep track of partition
        :param index: linear index
        :return: image, label, extra
        """
        # convert linear index into index respect to its partition
        label, class_index, index = self.__get_partitioned_index(index)
        path = self.dataset[label][index]

        extra = {
            'path': path,
            'label': label,
            'class_index': class_index,
            'inclass_index': index
        }

        # load and transform
        image = Image.open(path).convert('RGB')
        transformed_image = self.transform(image)

        # return image and label
        return transformed_image, class_index, extra

    def get_class_label(self, class_index):
        assert class_index < len(self.partition), 'The class_index is beyond number of class available'
        return self.partition[class_index][0]

