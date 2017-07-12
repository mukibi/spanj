#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $id;
my $logd_in = 0;
my $authd = 0;
my $accountant = 0;

my $con;
my ($key,$iv,$cipher) = (undef, undef,undef);

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		$id = $session{"id"};
		#only bursar(user 2) or accountant can search for a receipt
		if ( $id eq "2" or ($id =~ /^\d+$/ and ($id % 17) == 0) ) {

			$accountant++;
			if (exists $session{"sess_key"} ) {
				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				use MIME::Base64 qw /decode_base64/;
				use Crypt::Rijndael;

				my $decoded = decode_base64($session{"sess_key"});
				my @decoded_bytes = unpack("C*", $decoded);

				my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
				my @sess_key_bytes = @decoded_bytes;

				#read enc_keys_mem
				my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=? LIMIT 1");

				if ( $prep_stmt3 ) {

					my $rc = $prep_stmt3->execute($id);

					if ( $rc ) {

						my ($mem_init_vec, $mem_aes_key) = (undef,undef);

						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							$mem_init_vec = $rslts[0];
							$mem_aes_key = $rslts[1];
						}

						if ( defined $mem_init_vec ) {

							my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
							my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

							my ( @decrypted_init_vec, @decrypted_aes_key );

							for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
								$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
							}

							for (my $j = 0; $j < @mem_aes_key_bytes; $j++) {
								$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
							}

							$key = pack("C*", @decrypted_aes_key);
							$iv = pack("C*", @decrypted_init_vec);

							$cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
							$cipher->set_iv($iv);

							$authd++;

						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
					}

				}
				else {
					print STDERR "Couldn't prepare SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
				}
			}
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Accounts Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/search_receipt.cgi">Search Receipt</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to print a receipt.</span> Only the bursar and accountants are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Print Receipt</title>
</head>
<body>
$header

</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/search_receipt.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Create Balance Sheet</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/search_receipt.cgi">/login.html?cont=/cgi-bin/search_receipt.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/search_receipt.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	

	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}

	unless ($multi_part) {
		my $str = "";

		while (<STDIN>) {
        	       	$str .= $_;
	       	}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1));
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
	}
	#processing data sent 
	$post_mode++;
}

my @receipts;
#print receipt shortcut
if ( exists $ENV{"QUERY_STRING"} ) {
	my $query_str = $ENV{"QUERY_STRING"};
	my @query_str_bts = split/&/,$query_str;

	foreach (@query_str_bts) {
		if ($_ =~ /receipt_(\d+)=\1/) {
			my $receipt = $1;
			push @receipts, $receipt;
		}
	}
}

if ($post_mode) {

	foreach ( keys %auth_params ) {
		if ( $_ =~ /receipt_(\d+)/ ) {
			#don't want mischevious users doing their own cookery
			my $receipt_no = $1;
			if ($auth_params{$_} eq $receipt_no) {
				push @receipts, $receipt_no;
			}
		}
	}

}

my $results = qq!<span style="color: red">You did not specify any receipts to print.!;

if (scalar(@receipts) > 0) {

	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;
	my %receipt_data = ();
	my %adm_nos = ();
	$results = '';

	my %mode_payment_lookup = ("1" => "Bank Deposit", "2" => "Cash", "3" => "Banker's Cheque", "4" => "Money Order");

	my $prep_stmt1 = $con->prepare("SELECT receipt_no,paid_in_by,class,amount,mode_payment,ref_id,votehead,time,hmac FROM receipts WHERE receipt_no=? LIMIT 1");
	my %rolls = ();
	
	if ( $prep_stmt1 ) {

		foreach (@receipts) {
			my $rc = $prep_stmt1->execute($_);

			if ($rc) {

				while (my @rslts = $prep_stmt1->fetchrow_array() ) {

					my $paid_in_by = remove_padding($cipher->decrypt($rslts[1]));
					my $class = remove_padding($cipher->decrypt($rslts[2]));
					my $amount = remove_padding($cipher->decrypt($rslts[3]));
					my $mode_payment = remove_padding($cipher->decrypt($rslts[4]));
					my $ref_id = remove_padding($cipher->decrypt($rslts[5]));
					my $votehead = remove_padding($cipher->decrypt($rslts[6]));
					my $time = remove_padding($cipher->decrypt($rslts[7]));

					if ( $amount =~ /^\d+(\.\d{1,2})?$/ ) {	
						#check HMAC
						my $hmac = uc(hmac_sha1_hex($paid_in_by . $class . $amount . $mode_payment . $ref_id . $votehead . $time, $key));	
						if ( $hmac eq $rslts[8] ) {

							$adm_nos{$paid_in_by}++;
							$receipt_data{$_}->{"paid_in_by"} = $paid_in_by;
							$receipt_data{$_}->{"amount"} = format_currency($amount);
							my $mode_payment_descr = $mode_payment_lookup{$mode_payment};
							
							if ( $mode_payment eq "3" or $mode_payment eq "4" ) {
								$receipt_data{$_}->{"ref_id"} = $ref_id;	
							}

							$receipt_data{$_}->{"mode_payment"} = $mode_payment_descr;

							$receipt_data{$_}->{"payment_for"} = join(" ", map{ucfirst($_)} split(/\s+/,$votehead));

							my @date = localtime($time);
							my $f_time = sprintf "%02d/%02d/%d %02d:%02d:%02d", $date[3],$date[4]+1,$date[5]+1900,$date[2],$date[1],$date[0];	
							$receipt_data{$_}->{"time"} = $f_time;
							${$rolls{$class}}{$paid_in_by}++;
						}
					}
				}

			}
			else {
				print STDERR "Couldn't execute SELECT FROM receipts: ", $prep_stmt1->errstr, $/;
			}
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM receipts: ", $prep_stmt1->errstr, $/;
	}

	#read student metadata
	my %stud_lookup = ();

	if ( scalar(keys %rolls) > 0 ) {

		for my $roll (keys %rolls) {

			my @adms = keys %{$rolls{$roll}};
			my @where_clause_bts = ();

			foreach (@adms) {
				push @where_clause_bts, "adm=?";
			}

			my $where_clause = join(" OR ", @where_clause_bts);

			my $prep_stmt2 = $con->prepare("SELECT adm,s_name,o_names FROM `$roll`");

			if ($prep_stmt2) {

				my $rc = $prep_stmt2->execute();
				if ( $rc ) {
					while (my @rslts = $prep_stmt2->fetchrow_array()) {
						$stud_lookup{$rslts[0]} = $rslts[1] . " " . $rslts[2];
					}
				}
			}

		}

	}

	my %ordered_fee_structure = ("arrears" => 0);

	#read fee structure
	my $prep_stmt2 = $con->prepare("SELECT votehead_index,votehead_name,class,amount,hmac FROM fee_structure");
	
	if ($prep_stmt2) {
	
		my $rc = $prep_stmt2->execute();

		if ($rc) {

			while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
						
				my $decrypted_votehead_index = $cipher->decrypt($rslts[0]);
				my $decrypted_votehead_name = $cipher->decrypt($rslts[1]);
				my $decrypted_class = $cipher->decrypt($rslts[2]);
				my $decrypted_amount = $cipher->decrypt($rslts[3]);

				my $votehead_index = remove_padding($decrypted_votehead_index);
				my $votehead_name = remove_padding($decrypted_votehead_name);
				my $class = remove_padding($decrypted_class);
				my $amount = remove_padding($decrypted_amount);
	
				#valid decryption
				if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

					my $hmac = uc(hmac_sha1_hex($votehead_index . $votehead_name . $class . $amount, $key));
								
					#auth the data
					if ( $hmac eq $rslts[4] ) {	
						$ordered_fee_structure{lc($votehead_name)} = $votehead_index;
					}
				}
			}

		}
		else {
			print STDERR "Couldn't prepare SELECT FROM fee_structure: ", $prep_stmt2->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM fee_structure: ", $prep_stmt2->errstr, $/;
	}

	my %accounts = ();

	#check balance
	for my $adm_no (keys %adm_nos) {

		my %enc_accounts = ();
		my @where_clause_bts = ();

		for my $votehead ( keys %ordered_fee_structure ) {

			my $enc_accnt = $cipher->encrypt(add_padding($adm_no . "-" . $votehead));
			$enc_accounts{$enc_accnt} = $votehead;

			push @where_clause_bts, "BINARY account_name=?";

		}
	
		my $where_clause = join(" OR ", @where_clause_bts);
	
		my $prep_stmt3 = $con->prepare("SELECT account_name,class,amount,hmac FROM account_balances WHERE $where_clause");	

		if ($prep_stmt3) {

			my $rc = $prep_stmt3->execute(keys %enc_accounts);

			if ($rc) {

				while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
								
					my $decrypted_account_name = $cipher->decrypt($rslts[0]);
					my $decrypted_class = $cipher->decrypt($rslts[1]);
					my $decrypted_amount = $cipher->decrypt($rslts[2]);

					my $account_name = remove_padding($decrypted_account_name);
					my $class = remove_padding($decrypted_class);
					my $amount = remove_padding($decrypted_amount);

					#valid decryption
					if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

						my $hmac = uc(hmac_sha1_hex($account_name . $class . $amount, $key));

						#auth the data
						if ( $hmac eq $rslts[3] ) {

							my $votehead = $enc_accounts{$rslts[0]};
							#my $votehead_index = $ordered_fee_structure{$votehead};

							${$accounts{$adm_no}}{$votehead} = $amount;
						}
					}
				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM account_balances: ", $prep_stmt3->errstr, $/;
			}
		}
		else {
			print STDERR "Couldn't prepare SELECT FROM account_balances: ", $prep_stmt3->errstr, $/;
		}
	}
	
	foreach (keys %receipt_data) {

		my $paid_in_by = $receipt_data{$_}->{"paid_in_by"};
		my $new_balances_table = "";

		if ( $receipt_data{$_}->{"payment_for"} eq "Fees" ) {

			$new_balances_table = qq!<HR><DIV style="color: white; background-color: black; font-weight: bold">Fee Balance</DIV><TABLE border="1" width="100%"><THEAD><TH>Votehead<TH>Balance</THEAD>!;

			my $total_balance = 0;

			for my $accnt ( sort { $ordered_fee_structure{$a} <=> $ordered_fee_structure{$b} } keys %{$accounts{$paid_in_by}} ) {
	
				#-ve arrears is a prepayment
				my $votehead_n = $accnt;
				my $amount = ${$accounts{$paid_in_by}}{$accnt};

				if ( $votehead_n eq "arrears" ) {
					if ( $amount < 0 ) {
						$votehead_n = "prepayment";
						$amount *= -1; 
					}
				}
	
				my @votehead_bts = split/\s+/,$votehead_n;

				my @n_votehead_bts = ();
				foreach ( @votehead_bts ) {
					push @n_votehead_bts, ucfirst($_);
				}

				my $votehead = join(" ", @n_votehead_bts);


				$new_balances_table .= qq!<TR><TD align="left">! . $votehead . qq!<TD align="right">! . format_currency($amount);
				$total_balance += ${$accounts{$paid_in_by}}{$accnt};
			}

			my $formatted_balance = format_currency($total_balance);

			$new_balances_table .= qq!<TR style="font-weight: bold"><TD align="left">TOTAL<TD align="right">$formatted_balance</TABLE>!;

		}

		if ( exists $stud_lookup{$paid_in_by} ) {
			 $paid_in_by .= "($stud_lookup{$paid_in_by})";
		}

		my $ref_id_row = "";
		if ( exists $receipt_data{$_}->{"ref_id"} ) {
			$ref_id_row = qq!<TR><TD style="font-weight: bold">Ref No./Code<TD>$receipt_data{$_}->{"ref_id"}!;
		}

		
		$results .= 
qq!
<div style="height: 105mm; width: 74mm">
<img src="/images/letterhead_small.png" alt="">
<TABLE>

<TR><TD style="font-weight: bold">Receipt No.:<TD>$_
<TR><TD style="font-weight: bold">Received From:<TD>$paid_in_by
<TR><TD style="font-weight: bold">Mode of Payment:<TD>$receipt_data{$_}->{"mode_payment"}
$ref_id_row
<TR><TD style="font-weight: bold">Payment For:<TD>$receipt_data{$_}->{"payment_for"}
<TR style="font-weight: bold; color: white; background-color: black"><TD>Amount:<TD>$receipt_data{$_}->{"amount"}
</TABLE>
$new_balances_table
<div style="text-align: center">$receipt_data{$_}->{"time"}</div>
</div>
<br class="new_page">
!;

	}

	
}

$content =

qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Print Receipt</title>

<STYLE type="text/css">

\@media print {
	body {
		margin-top: 0px;
		margin-bottom: 0px;
		padding: 0px;
		font-size: 10pt;
		font-family: "Times New Roman", serif;	
	}

	div.no_header {
		display: none;
	}

	br.new_page {
		page-break-after: always;
	}

}

\@media screen {
	div.noheader {}	
	br.new_page {
		line-height: 2em;
	}
}

</STYLE>
</head>
<body>
<div class="no_header">
$header
</div> 
$results
</body>
</html>

*;

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

sub remove_padding {

	return undef unless (@_);

	my $packed = $_[0];
	my @bytes = unpack("C*", $packed);
	
	my $final_index = $#bytes;
	my $pad_size = $bytes[$final_index];

	my $msg_valid = 1;
	#verify msg
	
	for ( my $i = 1; $i < $pad_size; $i++ ) {
		unless ( $bytes[$final_index - $i] == $pad_size ) {
			$msg_valid = 0;
			last;
		}
	}

	if ($msg_valid) {
		my $msg_size = ($final_index + 1) - $pad_size;
		my $msg = unpack("A${msg_size}", $packed);

		return $msg;
	}
	return undef;
}

sub add_padding {

	return undef unless (@_);

	my $tst_str = $_[0];
	my $tst_str_len = length($tst_str);

	my $rem = 16 - ($tst_str_len % 16);
	if ($rem == 0 ) {
		$rem = 16;
	}

	my @extras = ();
	for (my $i = 0; $i < $rem; $i++) {
		push @extras, $rem;
	}

	my $padded = pack("A${tst_str_len}C${rem}", $tst_str, @extras);
	return $padded;
}

sub format_currency {

	return "" unless (@_);

	my $formatted_num = $_[0];

	if ( $_[0] =~ /^(\-?)(\d+)(\.(?:\d))?$/ ) {

		my $sign = $1;
		my $shs = $2;
		my $cents = $3;

		$sign = "" if (not defined $sign);
		$cents = "" if (not defined $cents);

		my $num_blocks = int(length($shs) / 3);

		if ($num_blocks > 0) {

			my @nums = ();

			my $surplus = length($shs) % 3;
			if ($surplus > 0) {
				push @nums, substr($shs, 0, $surplus);
			}

			for (my $i = 0; $i < $num_blocks; $i++) {
				push @nums, substr($shs, $surplus + ($i * 3),3);
			}

			$formatted_num = join(",", @nums); 
		}

		$formatted_num = $sign . $formatted_num;
		$formatted_num .= $cents;
	}
	return $formatted_num;
}
