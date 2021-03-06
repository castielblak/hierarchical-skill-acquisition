import torch
import torch.nn as nn
import torch.nn.functional as F
import warnings

from torch.autograd import Variable

class VisualEncoder(nn.Module):
    def __init__(self):
        super(VisualEncoder, self).__init__()

        self.conv1 = nn.Conv2d(in_channels=3, out_channels=32, kernel_size=8, stride=4)
        self.conv2 = nn.Conv2d(in_channels=32, out_channels=64, kernel_size=4, stride=2)
        self.conv3 = nn.Conv2d(in_channels=64, out_channels=64, kernel_size=3, stride=1)
        self.linear = nn.Linear(in_features=64*7*7, out_features=256)

    def forward(self, img):
        '''
        input:
            img - size of (batch_size, num_timesteps, 3, 84, 84)
        output:
            encoding - size of (batch_size, num_timesteps, 256)
        '''
        batch_size = img.size()[0]
        num_timesteps = img.size()[1]

        encoding = F.relu(self.conv1(img.view(batch_size * num_timesteps, 3, 84, 84)))
        encoding = F.relu(self.conv2(encoding))
        encoding = F.relu(self.conv3(encoding))
        encoding = F.relu(self.linear(encoding.view(batch_size * num_timesteps, -1)))

        return encoding.view(batch_size, num_timesteps, -1)

class InstructionEncoder(nn.Module):
    def __init__(self, vocabulary_size, bow=True):
        '''
        vocabulary_size - number of words in the target vocabulary
        bow - whether to use bag of words or rnn-encoding
        '''
        super(InstructionEncoder, self).__init__()

        self.bow = bow
        self.vocabulary_size = vocabulary_size
        self.embeddings = nn.EmbeddingBag(vocabulary_size, 128, mode="sum")

    def forward(self, instruction):
        '''
        input:
            instruction - a list of [[int, int, int, ...]], size of (batch_size, sequence_length)
        output:
            embedding - size of (batch_size, 128)
        '''
        if(not self.bow):
            warnings.warn("The RNN-encoding is not yet implemented. Switch to the Bag of Words.")

        #batch_size = instruction.size()[0]
        #offset = torch.zeros(batch_size).type(torch.LongTensor)
        return self.embeddings(instruction, None)        
        
class Fusion(nn.Module):
    def forward(self, visual_encoding, instruction_encoding):
        '''
        input:
            visual_encoding - size of (batch_size, num_timesteps, 256)
            instruction_encoding - size of (batch_size, 128)
        output:
            fusion - [batch_size, num_timesteps, 384]
        '''
        batch_size = visual_encoding.size()[0]
        num_timesteps = visual_encoding.size()[1]
        instruction_expanded = instruction_encoding.unsqueeze(1).expand(batch_size, num_timesteps, 128)

        return torch.cat([visual_encoding, instruction_expanded], -1)

class TimeEncoder(nn.Module):
    '''
    Refer to the LSTM-module in the original paper.
    We need this encoder in order to capture time dependencies.
    Thus get rid of stacking multiple frames. Shown to be slightly better for POMDP (https://arxiv.org/abs/1507.06527)
    '''
    def __init__(self):
        super(TimeEncoder, self).__init__()

        self.hidden_size = 256
        self.lstm = nn.LSTM(input_size=384, hidden_size=self.hidden_size, batch_first=True)

    def forward(self, fused):
        '''
        input:
            fused - size of (batch_size, num_timesteps, 384)
        output:
            time_encoded - size of (batch_size, 256)
        '''
        batch_size = fused.size()[0]
        
        # Hidden state must be initialized with zeros
        hidden = (Variable(torch.zeros(batch_size, self.hidden_size)),
                  Variable(torch.zeros(batch_size, self.hidden_size)))
        output, hidden = self.lstm(fused, hidden)

        return hidden[0].squeeze(0)

class SwitchPolicy(nn.Module):
    def __init__(self):
        super(SwitchPolicy, self).__init__()

        self.linear = nn.Linear(in_features=256, out_features=2)

    def forward(self, time_encoded):
        '''
        input:
            time_encoded - a tensor of size (batch_size, 256)
        output:
            switch - a tensor of size (batch_size, 2)
        '''
        return F.softmax(self.linear(time_encoded), dim=-1)

class InstructionPolicy(nn.Module):
    def __init__(self, num_instructions, num_objects):
        super(InstructionPolicy, self).__init__()

        self.num_instructions = num_instructions
        self.num_objects = num_objects
        self.instruction_linear = nn.Linear(in_features=256, out_features=num_instructions)
        self.object_linear = nn.Linear(in_features=256, out_features=num_objects)

    def forward(self, time_encoded):
        '''
        input:
            time_encoded - a tensor of size (batch_size, 256)
        output:
            instruction_probs - a tensor of size (batch_size, num_instructions)
            object_probs - a tensor of size (batch_size, num_objects)
        '''
        instruction_probs = F.softmax(self.instruction_linear(time_encoded), dim=-1)
        object_probs = F.softmax(self.object_linear(time_encoded), dim=-1)

        return instruction_probs, object_probs

class AugmentedPolicy(nn.Module):
    def __init__(self, num_actions):
        super(AugmentedPolicy, self).__init__()

        self.num_actions = num_actions
        self.linear = nn.Linear(in_features=256, out_features=num_actions)
    
    def forward(self, time_encoded):
        '''
        input:
            time_encoded - a tensor of size (batch_size, 256)
        output:
            action_probs - a tensor of size (batch_size, num_actions)
        '''
        action_probs = F.softmax(self.linear(time_encoded), dim=-1)
        return action_probs

if __name__ == "__main__":
    BATCH_SIZE = 10
    NUM_TIMESTEPS = 4

    # TESTING: Instruction part
    instr_input = Variable(torch.LongTensor(BATCH_SIZE, 5).random_(0, 10))
    instr_encoder = InstructionEncoder(10)
    instr_encoding = instr_encoder.forward(instr_input)
    assert(instr_encoding.size() == (BATCH_SIZE, 128))
    print("Instruction encoder: Output size is verified.")

    # TESTING: Visual part
    visual_input = Variable(torch.randn(BATCH_SIZE, NUM_TIMESTEPS, 3, 84, 84))
    visual_encoder = VisualEncoder()
    visual_encoding = visual_encoder.forward(visual_input)
    assert(visual_encoding.size() == (BATCH_SIZE, NUM_TIMESTEPS, 256))
    print("Visual encoder: Output size is verified.")

    # TESTING: Fusion part
    fuser = Fusion()
    fused_encoding = fuser.forward(visual_encoding, instr_encoding)
    assert(fused_encoding.size() == (BATCH_SIZE, NUM_TIMESTEPS, 384))
    print("Fuser encoding: Output size is verified.")

    # TESTING: Time-encoder part
    time_encoder = TimeEncoder()
    time_encoding = time_encoder.forward(fused_encoding)
    assert(time_encoding.size() == (BATCH_SIZE, 256))
    print("Time encoder: Output size is verified.")

    # TESTING: Switch policy
    switch_policy = SwitchPolicy()
    switch = switch_policy.forward(time_encoding)
    assert(switch.size() == (BATCH_SIZE, 2))
    print("Switch policy: Output size is verified.")

    # TESTING: Instruction policy
    instruction_policy = InstructionPolicy(num_instructions=4, num_objects=6)
    instruction, obj = instruction_policy.forward(time_encoding)
    assert(instruction.size() == (BATCH_SIZE, 4))
    assert(obj.size() == (BATCH_SIZE, 6))
    print("Instruction policy: Output sizes are verified.")

    # TESTING: Augmented policy
    augmented_policy = AugmentedPolicy(num_actions=8)
    action_probs = augmented_policy.forward(time_encoding)
    assert(action_probs.size() == (BATCH_SIZE, 8))
    print("Augmented policy: Output size is verified.")